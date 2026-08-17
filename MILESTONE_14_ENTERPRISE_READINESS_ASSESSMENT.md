# Milestone 14: Enterprise Readiness Assessment

Both sections below are **recommendations only**. Nothing in this document was implemented; any
schema or infrastructure change described here requires explicit approval before any work begins, per
this milestone's own instructions.

## Workstream 10: Legacy `documents` table -- disposition recommendation

**Facts, re-verified this milestone against current code (not merely carried forward from Milestone 13's
findings)**:
- `Document` (table `documents`) has no `organization_id` column and no derivable ownership chain of
  its own.
- Two independent nullable foreign keys reference it: `Authority.document_id` and
  `Principal.source_document_id`.
- Zero live write path: `upload_document`, `review_authority`, `compile_policy`, and `activate_policy`
  in `server/app/routers/policies.py` all unconditionally raise `HTTPException(410, ...)` as their
  first statement.
- One live read path: `GET /v1/policies/documents`, gated by `Permission.AUDIT_EXPORT`, Owner-only
  (no per-organization scoping is structurally possible on this table).
- Zero SDK or frontend consumers (the frontend's own `LiveDocument`/`LiveAuthority` types are dead
  code -- see BUG-022).
- Zero rows confirmed in production, verified via the authenticated API (not raw DB access, which
  remains blocked in this environment) as of Milestone 13; nothing in this codebase has any way to
  write a new row, so this has not changed.
- The AI Authority Builder's `authority_corpus_documents` table is a genuinely separate, modern,
  organisation-scoped pipeline with its own write path (`ai_authority_builder_service.add_document`)
  -- Enterprise Knowledge would build on this, not on the legacy `documents` table, regardless of which
  option below is chosen.

**Option A -- retain but formally deprecate.** No schema change. Document the table and its two FKs as
legacy in `ARCHITECTURE.md`/`SPECIFICATION/17_LEGACY_COMPONENTS.md` (already partially done). Lowest
short-term effort, zero migration risk. Cost: the two dangling, unexplained FK columns and the dead
`GET /v1/policies/documents` endpoint remain in the schema and API surface indefinitely as landmines
for a future engineer who doesn't have this document's context, and Enterprise Knowledge's own data
model has to be designed around and explicitly distinguished from a superficially similar legacy
concept forever.

**Option B -- remove references and retire the table.** Drop the `documents` table and the two FK
columns (`Authority.document_id`, `Principal.source_document_id`), delete the four `410`-only legacy
router functions and the `GET /v1/policies/documents` endpoint entirely, delete the two dead frontend
types. Requires a real Alembic migration against the production schema. Zero production rows and zero
write path make this operationally safe in principle, but it is still a schema-altering migration
against a live production database, which this engagement's own standing practice never performs
without a dedicated, explicitly-approved step -- correctly out of scope to execute unilaterally this
milestone.

**Option C -- migrate references into the current scoped corpus architecture.** Since zero rows exist
to migrate, this reduces in practice to Option B: there is no real data-preservation problem to solve,
so "migrating" the (nonexistent) data and then retiring the old table is the same end state as Option
B, just described as a migration rather than a removal.

**Recommendation: Option B**, sequenced as two separate steps rather than one:
1. **Low-risk, achievable without a schema migration**: deprecate `GET /v1/policies/documents` now (mark
   it clearly, or remove the endpoint itself, since it has zero known consumers) and delete the two
   dead frontend types (BUG-022). This alone removes the only live-but-vestigial surface without
   touching the database.
2. **Requires explicit approval, not performed this milestone**: schedule the actual `DROP TABLE`/
   `DROP COLUMN` Alembic migration as its own dedicated, reviewed step. Given zero rows and zero write
   path, the risk is low, but "low risk" is not the same as "no approval needed" for an irreversible
   schema change against production.

## Workstream 11: Blob Storage / Azure AI Search tenant hardening -- proposal

**Current state, re-verified this milestone**: `services/authority_intelligence_service.py` uses one
shared Blob container and one shared Azure AI Search index across every organization. Isolation is
enforced entirely at the application layer: a blob-path naming convention
(`authority-corpora/{org_id}/{corpus_id}/{doc_id}-{filename}`) and a string-interpolated OData filter
(`corpus_id eq '{corpus_id}' and organization_id eq '{org_value}'`, both internally-generated UUIDs, so
injection risk is low). Every code path checked in Milestone 13 correctly applies this filter; there is
no independent backstop if a future caller forgets to.

**Target architecture** (as specified by the milestone's own instructions, not altered here):
Organization → Scoped Corpus → Scoped Blob Objects → Scoped Search Documents → Scoped Retrieval →
Scoped Evaluation, with app-level authorization mandatory but tenant separation not solely dependent on
developer discipline.

**Proposed hardening, ordered cheapest-and-safest first, none implemented this milestone**:

1. **Centralize filter construction.** If the OData filter string is not already built by exactly one
   function every caller must use, make it so (e.g. a single `_scoped_filter(org_id, corpus_id)`
   helper). This is a pure refactor, no infrastructure change, and directly reduces "a future caller
   forgets the filter" from a real risk to a much smaller one, since there is only one place to get it
   right.
2. **Defense-in-depth response check.** After any Search query returns, assert every result's own
   `organization_id`/`corpus_id` fields match the caller's expected scope before returning them; log
   and drop (fail closed) any mismatch instead of returning it. This is the actual "backstop that
   doesn't depend solely on developer discipline" the milestone asks for, achievable in application
   code with no schema or infrastructure change -- if the query-side filter is ever wrong or bypassed,
   this catches it before data crosses the tenant boundary.
3. **Scope any direct Blob access.** If any code path ever issues a direct Blob URL or SAS token to a
   frontend or external consumer (not confirmed to exist today, but worth checking before Enterprise
   Knowledge adds new consumers), that token should be scoped to the specific blob prefix for that
   organization/corpus, not container-wide.
4. **Not proposed for now**: per-organization Search indexes or per-organization Blob containers.
   Azure AI Search supports this, but it carries real cost and quota implications at scale and is a
   heavier operational commitment than items 1-3. Worth revisiting only if a real Enterprise Knowledge
   requirement demands true storage-layer isolation (e.g. a customer's contractual requirement for
   physical data segregation) -- premature to build speculatively.

**Recommendation**: implement items 1-2 as a pre-Enterprise-Knowledge hardening pass -- both are
code-only, no schema or infrastructure changes, low risk, and they directly close the MEDIUM/WARNING
finding's actual mechanism (missing independent backstop) rather than its symptom. Defer items 3-4
pending concrete Enterprise Knowledge requirements that would justify their cost.

## Overall Enterprise Knowledge readiness

See `MILESTONE_14_COMPLETION_SUMMARY.md` for the explicit gate decision. In summary: this milestone
closed real, verified P0-adjacent gaps (RBAC controls implying available actions the backend rejects,
an unconfirmed destructive action on tenant organizations, several silent-failure/infinite-loading
defects) and closed a real, previously-undiscovered production deployment drift. It did not complete
an exhaustive page-by-page RBAC sweep, a full live browser verification pass (tooling unavailable), or
a comprehensive frontend test suite beyond the highest-value pure-logic module. Enterprise Knowledge
work should not begin until those remaining gaps are either closed or explicitly accepted as residual
risk by the person who owns that decision.
