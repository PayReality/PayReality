# AI Authority Builder: Architecture

## What changed from AI Policy Builder

The AI Policy Builder (previous phase) took one document and produced candidate Runtime Policies. The AI Authority Builder takes an **Authority Corpus**, a set of one or more documents uploaded together and analyzed as a single body of evidence about one organisation's authority structure, and produces a full **Authority Graph**: Runtime Policy candidates, but also the Principals, Resources, Operations, Relationships (delegation/escalation/inheritance chains), Conflicts, Gaps (missing information), and clarification Questions the model found across the whole corpus.

This is additive, not a rewrite. Every table, service function, and API endpoint the AI Policy Builder built is preserved unmodified: `policy_extraction_uploads`, single-document upload, and the existing promote/dismiss/edit flow for a candidate all still work exactly as before. The AI Authority Builder is a new layer that produces *more kinds* of discovered objects from *more than one document at once*, and reuses the existing candidate machinery for the one kind of object both systems share (Runtime Policy candidates).

## Why this is additive, not a replacement

`services/ai_policy_builder_service.py`'s `promote_candidate`, `dismiss_candidate`, and `edit_candidate` operate on a `PolicyExtractionCandidate` row by id; they have no idea whether that row came from a single-document upload or a multi-document corpus. This phase makes exactly two changes to that existing table, both backward-compatible: `upload_id` becomes nullable (a corpus-derived candidate has no single owning upload) and a new nullable `corpus_id` column is added (a `CHECK` constraint enforces exactly one of the two is set, never both, never neither). Every existing row, and every existing single-upload API call, is unaffected: `upload_id` is still always set for anything created through the original `/v1/ai-policy-builder/uploads` endpoint, which itself is untouched.

## The corpus model

An `AuthorityCorpus` (`authority_corpora`) is the unit of analysis: one or many uploaded documents (`authority_corpus_documents`), extracted and analyzed together in a single LLM call, never document-by-document. The directive's own instruction, "treat all uploaded files as ONE Authority Corpus, never analyse documents independently," is implemented literally: `text_extraction.extract_text` (imported unchanged from the AI Policy Builder) runs once per document to get that document's own marked-up text, and those per-document texts are concatenated with a `=== FILE: <filename> ===` header before the single extraction call, so the model sees the whole corpus as one body of evidence and can, for example, notice that one document's delegation limit contradicts another's.

## The Authority Graph

One extraction call returns, via forced tool-use (the same structural guarantee against generating Rego or deploying that `PROMPT_LIBRARY.md` established: the tool schema has no field for either), all of:

- **Policies**: identical shape to the AI Policy Builder's candidates, stored in the same `policy_extraction_candidates` table, promoted through the same, unmodified `promote_candidate`.
- **Principals**: every authority holder named, with an optional `reports_to` for reconstructing a reporting hierarchy.
- **Resources** and **Operations**: every business object and verb named across the corpus, informational (there is no first-class "Resource" or "Operation" table anywhere else in the platform yet, per `DOMAIN_AGNOSTIC_ARCHITECTURE.md`; these rows describe what the organisation's documents say, they do not create new enforceable vocabulary anywhere else in this phase).
- **Relationships**: delegation, escalation, or inheritance links between named principals, as the model found them stated or implied.
- **Conflicts**: contradictory or duplicate authority the model noticed across documents. This is model-reported, reviewed by a human, never a formal constraint-satisfaction proof; the UI never claims otherwise, the same "never oversell a heuristic" discipline Compiler V2's own bounded conflict detection already holds itself to.
- **Gaps**: missing information the model expected to find and didn't (an undefined approver, an unstated limit, a resource mentioned but never scoped).
- **Questions**: clarification questions the model generated for a human reviewer, not confidence-scored (a question is a request for information, not a claim to be confident or unconfident about); a reviewer can mark one answered and record the answer.

Every item in every category carries `confidence`, `source_excerpt`, and `source_location` (which document and where), exactly as the AI Policy Builder's candidates already do, so nothing here introduces a new epistemic standard, only more categories held to the existing one.

## What the AI can never do (structural, not just prompted)

Identical guarantees to the AI Policy Builder, extended to every new category: the tool schema has no field for Rego, source code, or a deploy/activate instruction anywhere in it, for any of the eight categories. The only category with a promotion path into a real, enforceable system object is Policies, via the completely unmodified `runtime_policy_service.create_policy`. Resources, Operations, Conflicts, and Gaps have no "promote" action at all, because there is no first-class system table for any of them to promote into; they exist purely as reviewable, cited findings. Questions can only be marked answered, never auto-resolved.

**Correction to the original claim above (this document predates it):** Principals and Relationships *do* now have a real, but narrow and non-Rego, resolution path — `resolve_principal`/`resolve_relationship`/`activate_relationship` (`services/ai_authority_builder_service.py`), covered in full in `SPECIFICATION/09_AI_AUTHORITY_BUILDER.md` and `SPECIFICATION/17_LEGACY_COMPONENTS.md`. Resolving a Principal creates a real `Principal` row; activating a Relationship makes it count in live enforcement, but only as read-time context (`authority_context_service.resolve_runtime_authority_context`) that a Rego condition *may* reference — it is never itself compiled into a Rego rule. That distinction (context enrichment vs. compiled policy) is confirmed architectural precision, not drift, per the Authority Intelligence Program Phase 2 report's own architecture-conformance review.

## Explainability, Conflict Workspace, Coverage, and Approval Audit (Phase 3)

`EXPLAINABILITY_MODEL.md`'s scope, summarized here since it lives directly on top of the Authority Graph above:

- **Explainability fields**: every Principal, Resource, Operation, Relationship, and Policy candidate carries four additional first-class columns — `clause_reference` (the document's own internal numbering, e.g. "Clause 4.2," distinct from `source_location`'s page/paragraph marker), `extraction_reasoning` (why the model concluded this — a direct statement or an inference), `detected_assumptions`, and `ambiguity_flags`. All four are asked of the model via the same forced tool-use schema as `confidence`/`source_excerpt` always have been — never inferred after the fact, never buried inside free-form output.
- **Conflict Workspace**: every Conflict now carries a `conflict_type` (authority/threshold/role/policy/delegation/circular_delegation) and a `reviewer_recommendation`. The type is the model's own classification (or, for `circular_delegation`, independent deterministic graph-cycle detection over the corpus's own delegation edges, `detect_circular_delegations`); the recommendation is *always* computed in Python from `conflict_type`/`confidence`, never asked of the model — this platform never auto-resolves a conflict, so every recommendation says so, only the wording differs.
- **Missing Information Detection**: `detect_missing_information` is a deterministic, code-computed pass over already-persisted rows (unknown reporting lines, unresolved relationships, policies with no numeric limit for a money-moving action, delegations with no stated source), independent of and a backstop for the model's own self-reported Gaps/Questions.
- **Coverage Analysis**: `text_extraction.extract_text_with_coverage` (a new function; the original `extract_text`, still used by the single-document AI Policy Builder, is unchanged) returns deterministic parsing statistics alongside the marked-up text — clauses analysed/ignored, tables extracted, images skipped — aggregated per corpus via `get_coverage`. Never an LLM's self-report of its own completeness.
- **Graph Diff**: `get_graph_diff` compares a corpus's candidate graph against the Authority Graph already in force for the same organisation (new/removed authorities, changed thresholds, changed reporting lines/responsibilities) — a deterministic set/value comparison; the extraction model's job ends at extraction time.
- **Approval Audit**: `approve_graph` appends one immutable `authority_graph_approvals` row (reviewer, version, an evidence snapshot, an optional reason, and a `graph_hash` reusing `domain/evidence/signing.py`'s canonicalize/hash pattern unchanged) recording that a human reviewed this corpus's graph. It is strictly additive: it does not itself resolve, activate, or promote anything, and calling it a second time creates the next version rather than overwriting the first.

None of this changes the promotion boundary above: it makes the existing boundary visible and auditable, it does not move it.

## Authority Graph Lineage & Versioning (issue #5)

Approval Audit (above) gives every approved graph version an immutable snapshot. This closes the two questions that left open: what approved version came immediately before this one, and what exactly changed between them.

**Predecessor, not a second "version" concept.** `AuthorityGraphApproval.predecessor_approval_id` is one additive, nullable, self-referential column, stamped once by `approve_graph` to the corpus's real latest approval at that exact moment (null only for a corpus's first approved version) and never changed afterward. There is no separate `AuthorityGraphVersion` table and no change to how `version` itself is assigned (still `max(version) + 1` per corpus) — lineage is a pointer layered on top of the existing approval record, not a parallel versioning system. "What superseded this version" (`superseded_by_approval_id` in API responses) is never itself stored; it's always derived by reverse lookup (`get_superseding_approval`: which row, if any, has this row's id as its own predecessor) — one direction of truth, not two fields that could drift apart.

**Lineage is corpus-local, always.** A predecessor is only ever a prior approval of the *same* corpus. Two corpora approved in an interleaved order never cross-contaminate each other's lineage, and a diff request naming an `against` approval from a different corpus (or, transitively, a different organisation) 404s rather than comparing across boundaries — `get_approval_for_corpus` is the one function every lineage/diff read goes through, the same "path segments must agree" discipline the rest of this router already applies.

**Concurrency.** No row locking exists anywhere in this codebase, by established preference. Two `approve_graph` calls racing for the same corpus can both read the same "current latest" before either commits and compute the same next version number; the database's own `uq_authority_graph_approvals_corpus_version` constraint — not a lock — is what actually prevents both from persisting. The loser's `IntegrityError` is caught, the version and predecessor recomputed against the now-current latest, and the insert retried, bounded at three attempts (`ConcurrentApprovalConflictError` beyond that, mapped to HTTP 409) — never an unhandled 500, never an infinite loop.

**The diff itself (`domain/authority_graph/diff.py`) is pure and deterministic** — no database call, no LLM call, no network call, same discipline as this package's own `compilation_gate.py`. It compares two `evidence_snapshot` dicts by each item's own stable `id` (the underlying `AuthorityPrincipal`/`AuthorityRelationship`/`AuthorityConflict`/`AuthorityGap` row id) into added/removed/changed sets, plus a field-by-field coverage comparison. That identity is stable across a corpus's approval history today because `run_extraction` only ever runs once per corpus — every later reviewer action mutates an existing row rather than recreating it — not a deliberately designed cross-version identity scheme; if a "re-extract this corpus" capability is ever added, this assumption needs re-verifying. Resources, Operations, and Questions are extracted per corpus but never included in `evidence_snapshot`, so they cannot be diffed today — a real, disclosed limitation of what gets captured at approval time, not of the diff engine. Conflicts have no structured link to which principal/action they concern (only a free-text description), so a conflict diff can only ever say "this conflict appeared/disappeared/changed," never attribute *why* structurally.

**Worked example**, in the same shape a reviewer sees on Approval History's "View changes":

```
Graph v1 (approved):
  David Okonkwo -- vendor_payment <= $50,000

Graph v2 (approved):
  David Okonkwo -- vendor_payment <= $50,000   (unchanged)
  AP Agent      -- vendor_payment <= $50,000   (new principal + relationship)
  Sarah Mokoena -- escalation authority above $50,000   (new)

Changes from v1 to v2:
  Principals:      + AP Agent, + Sarah Mokoena
  Relationships:    + David -> AP Agent (delegation), + Sarah -> escalation
  Conflicts:        0 introduced, 0 resolved
  Gaps:             0 introduced, 0 resolved
  Coverage:         unchanged
```

Approving v2 does not retire, mutate, or deactivate anything compiled from v1 — that remains entirely the existing, separate `promote_candidate` / RuntimePolicy review-approve-compile-activate lifecycle, exactly as before this milestone. A Decision made under a RuntimePolicy compiled from v1 stays bound to v1 forever (Historical Policy Binding, unrelated to and unmodified by this milestone): its `policy_id` -> `Policy.bundle_manifest` -> `source.graph_approval_id`/`graph_version` chain is frozen at compile time and never re-resolves, proven end-to-end by `test_old_decision_and_receipt_stay_bound_to_graph_v1_after_v2_supersedes_it` (issue #6's own test, still green).

**API**: `GET /corpora/{corpus_id}/approvals/{approval_id}/diff`, defaulting to a comparison against the approval's own predecessor; `?against=<approval_id>` compares against any other approval from the same corpus instead. 404s (not an empty or nonsensical diff) if the approval doesn't exist, belongs to a different corpus, or (with no explicit `against`) has no predecessor at all.

## Why the module isn't renamed on disk

The directive asks that the *product* be renamed from AI Policy Builder to AI Authority Builder. The user-facing surface (navigation, page titles, the entry point from Policy Studio) reflects that rename directly. The underlying Python package (`domain/ai_policy_builder/`, `services/ai_policy_builder_service.py`) is deliberately left in place and untouched: it is still exactly correct for what it does (single-document, Runtime-Policy-only extraction), it is imported by the new `domain/ai_authority_builder/` package rather than duplicated, and renaming already-shipped, already-tested modules purely for naming symmetry would be exactly the kind of unforced churn this multi-phase engagement has consistently avoided (see `RUNTIME_POLICY_MAPPING.md`'s and `DOMAIN_AGNOSTIC_ARCHITECTURE.md`'s own preference for reuse over renaming-for-its-own-sake). A new user only ever sees "AI Authority Builder"; which files implement it is an internal detail this document exists to explain, not something the product surface needs to expose.
