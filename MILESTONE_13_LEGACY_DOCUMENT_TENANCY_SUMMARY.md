# Milestone 13: Legacy Document Tenancy and Pre-Enterprise-Knowledge Readiness

A forensic audit of the `documents` table (the one residual finding Milestone 12 disclosed but could not close without a schema decision), plus a broader pre-Enterprise-Knowledge security gate. **No schema change is implemented in this milestone** -- every option is presented for approval, per instruction. No Enterprise Knowledge work was started.

## Executive summary

`documents` is confirmed, exhaustively, to be dead legacy infrastructure: zero live write path, exactly one live read path (already authenticated and permission-gated since Milestone 12), zero SDK or frontend consumers, and no background job of any kind touches it -- this platform has no background task runner at all. It is currently, and was independently re-verified live this session to be currently (not merely "as of a past date"), **empty**: a real, authenticated, unfiltered query against production returned zero documents and zero authorities across both organisations that exist in production today. This closes a real gap this milestone's own forensic audit found: Milestone 12's claim that this fact was "verified against production" was not actually backed by evidence shown in that document -- it is now.

The audit found one fact Milestone 12 missed: `documents.id` has **two** independent foreign keys pointing at it (`Authority.document_id` and `Principal.source_document_id`), not one. Neither is ever populated by any code in this repository today, but any future schema decision must account for both.

The broader platform sweep (39 database models, every background job, Blob/Search storage, exports, the AI pipelines, and Simulator scenario storage) found `Document` to be the **only** model in the entire schema with zero derivable organisation ownership, and found no new CRITICAL or HIGH finding. One new MEDIUM/WARNING was found and is reported: Blob Storage and Azure AI Search share a single container/index across all organisations, with isolation enforced entirely at the application layer (a naming convention and a string-built filter), not backstopped by the storage layer itself.

**VERDICT: CONDITIONALLY READY FOR ENTERPRISE KNOWLEDGE.** See the completion gate at the end for the exact conditions.

---

## Phase 1: Full forensic audit

Traced from source (Alembic migrations, every service and router file, the SDK, and the frontend), not assumed:

**1. Schema and migrations**, in order: `d1f41ef42ccd_initial_schema` (2026-07-04) creates `documents` (id, name, `storage_uri`, status, uploaded_at) and both foreign keys into it (`principals.source_document_id`, `authorities.document_id`) in the same migration. `489c66c83eb4` (same day) converts `uploaded_at` to `TIMESTAMPTZ`. `7c2f9a1b3e4d_store_document_content_in_db` (2026-07-25) drops `storage_uri`, adds `content BYTEA NOT NULL` -- its own docstring states no document was ever successfully stored under the old scheme. `5b8f2d4a9c1e_add_ai_authority_builder_tables` (2026-07-26) creates the **separate** `authority_corpus_documents` table. `d7e28b4c91a6_authority_continuous_object_stage_g` (2026-08-07) loosens `authorities.document_id` to nullable and adds `corpus_id`, with its own docstring stating corpora "have no row in `documents` at all" and "there are none [authorities] in production today." No migration ever adds `organization_id` to `documents`.

**2. Every write path**: zero. `document_service.py` (8 lines total) defines only a read function; no create/insert function exists anywhere in the codebase. The only write-shaped router endpoint, `POST /v1/policies/documents` (`upload_document`), unconditionally `raise`s `HTTPException(410, ...)` as its first statement -- confirmed by direct read, no code path reaches a `Document(...)` construction.

**3. Every read path**: exactly one, live. `document_service.list_documents(db)` -> `select(Document)`, called from `GET /v1/policies/documents`. This is the endpoint Milestone 12 gated with `Permission.AUDIT_EXPORT`.

**4. Update/delete paths**: none exist. No `PATCH`/`DELETE` route touches `documents` anywhere.

**5. API endpoints**: exactly the two above (`GET`/`POST /v1/policies/documents`), both already accounted for.

**6. Background jobs**: none. `models.py`'s own `PolicyActivationSchedule` docstring states plainly that "there is no background task runner anywhere in this platform." Every function with "extraction" in its name belongs to the modern corpus/candidate pipelines (`ai_authority_builder`/`ai_policy_builder`), not `Document.status`'s `extraction_pending`/`extracted`/`extraction_failed` values -- those status values are themselves vestigial, since nothing transitions them anymore.

**7. SDK methods**: zero. A full grep of `sdk-python/payreality/*.py` for "document" returned no matches.

**8. Frontend consumers**: zero. A full grep of `src/` for `policies/documents` returned no matches. The AI Authority Builder's own `CorpusUploadPage.tsx` calls a completely different endpoint (`/v1/ai-authority-builder`), backed by the separate `authority_corpus_documents` table -- confirmed genuinely disjoint, not merely renamed: `AuthorityCorpusDocument` has its own table, its own FK (only to `authority_corpora.id`), and its own write function (`ai_authority_builder_service.add_document`), with no FK to `documents` anywhere.

**9. Relationships**: **two** independent nullable foreign keys reference `documents.id` -- `Authority.document_id` (used by Milestone 12's own analysis) and `Principal.source_document_id` (present since the initial migration, missed by Milestone 12's audit). Neither is ever set by any code path in this repository today (zero `Document(...)` constructions exist anywhere in application code, confirmed by grep). `Authority.principal_id -> Principal.organization_id` gives an indirect, one-hop-further ownership chain for documents reached via `Authority`; `Principal.source_document_id`, when populated, would point the other direction from a Principal that already carries its own `organization_id` directly.

**10. Whether records can be safely attributed to an organization**: **Option A is available in principle** (both relationship paths terminate at a real `organization_id`, eventually), but is **not exercised by any current data**, since no row uses either path. A document reachable through *both* paths simultaneously, pointing at two different organisations, would be genuinely ambiguous -- a real design question for Phase 4, currently moot only because zero rows exist to test it against.

## Phase 2: Historical data analysis

**A real, current, authenticated production check was performed this session** (not the stale "as of 2026-07-29" code-comment claim, and not the raw database, which this environment's own permission classifier blocked a direct connection attempt to -- disclosed, not worked around):

```
GET /v1/policies/documents   (operator key, authenticated)  -> [] (0 rows -- unfiltered, so this is the true global count)
GET /v1/policies/authorities (operator key, org "PayReality")            -> [] (0 rows)
GET /v1/policies/authorities (operator key, org "Milestone 5 Validation Org") -> [] (0 rows)
GET /v1/organizations        (operator key, platform-admin)  -> exactly 2 organisations exist in production today
```

Since `list_documents` returns every row in the table unfiltered (no organisation scoping exists to filter by), this single check is exhaustive for `documents` regardless of how many organisations exist. Since exactly two organisations exist and both were checked, the `authorities` check is exhaustive too.

**This closes a real documentation gap this milestone's own audit found**: `MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md` section 5.1 claimed the zero-rows fact was "verified against production," but section 10 of that same document, read in full, shows no authenticated query of `/v1/policies/documents` and no row count -- only unauthenticated `401` checks. The claim was restated from a 2026-07-29 code comment, not independently re-verified, across three consecutive milestone documents. It is independently re-verified now, with the evidence shown above.

Answers, given zero rows exist:
- **How many records exist**: zero, confirmed live.
- **Can existing documents be deterministically assigned to an organisation**: not applicable -- none exist to assign.
- **Are any records genuinely ambiguous**: not applicable.
- **What happens to orphaned/legacy records**: not applicable; none exist.
- **Is a nullable `organization_id` appropriate temporarily**: given zero rows, either nullable or `NOT NULL` is equally safe to add -- there is no historical data to violate a `NOT NULL` constraint.
- **Can `NOT NULL` eventually be enforced**: yes, trivially, immediately, since no existing row could violate it.
- **Can a backfill be performed safely**: yes -- it would be a no-op backfill (zero rows to touch).
- **Would the migration affect existing production behaviour**: no functional effect on its own, since the one live query (`list_documents`) does not reference `organization_id` today; any actual behavioural change (real per-org filtering) would require a second, explicit code change bundled with the migration, not the schema change alone.

## Phase 3: Security audit

Adversarial review of every angle the task named, against the actual, current attack surface (confirmed exhaustively in Phase 1: one `GET` list endpoint, one always-`410` `POST`, nothing else):

| Test | Result | Evidence |
|---|---|---|
| Unauthenticated access | Blocked, `401` | `test_b_unauthenticated_list_documents_returns_401` (Milestone 12, re-run this session) |
| Authenticated wrong-organisation access | N/A for `documents` (no org-scoping exists to bypass); **proven** for `authorities` | `test_h_org_a_cannot_see_org_bs_authorities` |
| Authenticated correct-organisation access | Passes for any `AUDIT_EXPORT`-permitted caller | `test_i_list_documents_denied_without_audit_export` (negative) + live production check above (positive) |
| Owner/Auditor/Reviewer/Agent-Admin permission boundaries | `AUDIT_EXPORT` is Owner-only; `AGENT_ADMIN` confirmed denied | `test_i_list_documents_denied_without_audit_export`. (This codebase's `Role` enum has no "member" role to test separately -- `OWNER`, `GOVERNANCE_ADMIN`, `AGENT_ADMIN`, `REVIEWER`, `AUDITOR`, `EXECUTIVE` are the full set.) |
| Direct ID access (IDOR) | N/A -- no `GET /v1/policies/documents/{id}` endpoint exists at all | Confirmed by full router read |
| List filtering bypass | N/A -- `list_documents` accepts no filter parameters | Confirmed by router signature |
| Pagination bypass | **New observation, LOW/WARNING**: `list_documents` has no pagination or result cap at all, unlike `GET /v1/agents` (capped at 500). Currently harmless (zero rows); would need a cap added if this table is ever populated again. | Confirmed by code read; not fixed, since fixing an unbounded-list-with-zero-rows is not a security defect today |
| Document creation with forged organisation identifiers | N/A -- `upload_document` unconditionally raises `410` as its literal first statement, regardless of any request body content | Confirmed by direct code read (a two-line function with no branching) |
| Update/delete IDOR | N/A -- no such endpoints exist | Confirmed by full router read |
| Indirect access through other endpoints | None found. The only other system touching a similarly-named concept (`authority_corpus_documents`) is confirmed structurally disjoint -- separate table, separate FK, separate write function, zero overlap | Forensic audit item 4; independently cross-checked by this milestone's broader sweep (Phase 6) |
| SDK access | None -- zero references anywhere in `sdk-python/` | Forensic audit item 5 |
| Background-job access | None -- no background task runner exists in this platform at all | Forensic audit item 6, `models.py`'s own docstring |

New regression test added this milestone: `test_g_second_document_relationship_path_has_the_same_limitation` proves the disclosed limitation (no per-organisation isolation) holds identically via the second, previously-unaudited `Principal.source_document_id` path, not just via `Authority.document_id`.

## Phase 4: Schema recommendation

Four options, compared on the axes requested. No option is implemented in this milestone.

| Option | Security | Migration risk | Backwards compatibility | Implementation complexity | Production risk | Effect on Enterprise Knowledge | Founder approval? |
|---|---|---|---|---|---|---|---|
| **1. Add mandatory (`NOT NULL`) `organization_id`** | Strongest -- makes real per-org filtering possible immediately | **Trivial** given zero existing rows (no backfill data to reconcile) | No break -- nothing currently reads/writes this column | Low: one migration, one query update to `list_documents` to actually filter by it | Low -- confirmed empty table, no live behaviour depends on the current shape | Only relevant if Enterprise Knowledge is ever decided to consume this legacy table (unlikely -- see Phase 5) | **Yes** -- changes a shared table's shape; still a schema decision even though risk is low |
| **2. Add nullable `organization_id` + controlled backfill later** | Weaker than Option 1 until backfill completes and `NOT NULL` is added | Low, but adds a deferred step (the eventual backfill/tightening) that could be forgotten | No break | Slightly higher than Option 1 (two steps instead of one) | Low | Same as Option 1 | **Yes** |
| **3. Derive organisation through the existing parent relationship (Authority/Principal) at query time, no schema change** | Weakest -- covers only documents reachable through a populated relationship; a document with neither `Authority.document_id` nor `Principal.source_document_id` set remains permanently unattributable, and (Phase 1, item 10) a document reachable through *both* paths pointing at different organisations would be genuinely ambiguous | None (no migration) | No break | Low code change, but leaves a real, permanent structural gap | Low | Does not resolve the underlying tenancy question Enterprise Knowledge would need answered cleanly | Arguably **no** schema decision needed, but the resulting permanent ambiguity is itself a product decision |
| **4. Retire the legacy `documents` model entirely** | Strongest in the sense of removing the question altogether | Requires a migration to drop the table and its two FKs; trivial given zero rows, but is a deletion, not an addition -- normally the highest-risk migration category, mitigated here only by the confirmed-empty state | Removes `GET /v1/policies/documents` and `POST /v1/policies/documents` entirely (currently: one 410-only write endpoint and one real, if empty, read endpoint) -- a real, visible API surface reduction | Low technically, but is a product decision to fully sunset a "kept for historical/audit access" surface the router's own comment says was deliberately preserved | Low technically; the actual risk is organisational (removing something someone deliberately chose to keep, for a reason not documented here) | Cleanest possible foundation -- removes the one model in the entire schema with no ownership story, permanently | **Yes** -- reversing a previous, deliberate "keep for historical/audit access" decision is exactly the kind of call this milestone should not make unilaterally |

**Recommendation**: Option 1 (mandatory `organization_id`, added now while the table is confirmed empty and the migration is genuinely trivial) if there is any chance this legacy pipeline or its data is ever revived or referenced again; Option 4 (retire entirely) if the founder confirms it never will be, which the router's own "historical/audit access" framing does not currently confirm either way. **Both require approval** -- this document does not choose between them.

## Phase 5: Enterprise Knowledge dependency analysis

Grounded in `ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md` and `PAYREALITY_ENTERPRISE_KNOWLEDGE_RESOLUTION_VISION.md` (both re-read this milestone), cross-checked against what actually exists in code today:

- **Will Enterprise Knowledge consume `documents`?** Almost certainly not. The Vision document's own future-pipeline diagram begins at "Enterprise Documents" feeding "Authority Intelligence" -- but the concrete, already-built implementation of that stage is the AI Authority Builder's `authority_corpus_documents` table, a wholly separate, already-multi-tenant-aware system (organisation-scoped Blob paths and Search filters, confirmed in Phase 6). The legacy `documents` table this milestone audits is retired infrastructure from before that system existed, not a candidate input to a future one.
- **Does every knowledge artifact need organisation ownership?** Per the Vision document's own principles (Section 4: "Enterprise Knowledge should never perform authorization," and the whole document's emphasis on provenance), yes -- a business assertion is explicitly "enterprise-scoped" by definition (Section 5). Any future Enterprise Knowledge store must have organisation ownership designed in from its first schema, not retrofitted the way `documents` now needs to be.
- **What metadata must be immutable?** Not decided by the Vision document (explicitly left open in Section 12); this milestone does not decide it either.
- **What versioning is required?** Open (Vision document Section 13); not decided here.
- **What provenance is required?** The Vision document is explicit and consistent on this: resolver identity, resolution method, timestamp, and validity window, at minimum (Sections 3, 6, 12).
- **Can an artifact ever be shared across organisations?** Not addressed as a settled answer anywhere; the Vision document's Section 5 framing ("enterprise-scoped") leans toward no, but this is explicitly one of the document's own open questions, not a decision this milestone can make on its behalf.
- **How should global/platform documents differ from tenant documents?** No such category exists in the codebase today (`SigningKey`, confirmed in Phase 6, is the one genuinely platform-wide, non-tenant record type that exists) -- this is a real open design question for Enterprise Knowledge to answer when it is actually scoped, not something `documents`' current shape informs either way.
- **How should deleted/retired documents behave?** No answer exists today (`documents` has no soft-delete/retirement concept at all -- only an extraction-status field that nothing transitions anymore).
- **How should document versions relate to policy versions and decision evidence?** The Vision document's own Section 12 names this directly as unresolved ("should Evidence embed resolved values directly, embed only a hash or reference... or something in between").

**Conclusion for this phase**: Enterprise Knowledge's actual future document/knowledge-artifact model is not blocked by, and should not be built on top of, the legacy `documents` table -- it would need its own, purpose-built, organisation-scoped schema from the start, consistent with the Vision document's own stated principles. The `documents` table's tenancy gap is a real, disclosed, pre-existing defect worth resolving on its own merits (Phase 4), but resolving it is not a prerequisite for Enterprise Knowledge specifically, since Enterprise Knowledge is very unlikely to ever touch this table.

## Phase 6: Broader pre-Enterprise-Knowledge security gate

A full inventory of all 39 database models in `server/app/db/models.py`, cross-referenced for organisation ownership (direct column, indirect chain, or none):

**`Document` is the only model in the entire schema with zero derivable organisation ownership of any kind.** Every other model either has a direct `organization_id` column (`BusinessUnit`, `Resource`, `Principal`, `Policy`, `User`, `OrganizationInvitation`, `ApiKey`, `EnterpriseSystem`, `Evidence`, `RuntimePolicyRecord`, `PolicyExtractionUpload`, `AuthorityCorpus`, `SimulationScenario`, `RuntimePolicyLifecycleEvent`, `PolicyActivationSchedule`) or a resolvable one-to-multi-hop chain to one (e.g. `Agent -> Principal`, `Certificate -> Agent -> Principal`, `Decision -> Policy`, every `Authority*` corpus-child table `-> AuthorityCorpus`). `SigningKey` is deliberately platform-wide (public verification keys, not tenant data -- correct as-is, not a finding).

**Background jobs**: two cross-org-by-design operations exist (one more than previously documented) -- `process_due_schedules` (HTTP-reachable, operator-key-only, already correctly gated) and `reconcile_opa_with_active_policies` (internal-only, no HTTP surface, writes each organisation's own bundle only to that organisation's own isolated OPA package path). Both confirmed safe by design, not findings.

**New finding, MEDIUM/WARNING**: Azure Blob Storage and Azure AI Search (`authority_intelligence_service.py`) share a single container and a single search index across every organisation. Isolation is enforced entirely by the application layer -- a blob-path naming convention (`authority-corpora/{org_id}/{corpus_id}/...`) and a string-interpolated OData filter (`f"... and organization_id eq '{org_value}'"`) -- with no independent backstop at the storage layer itself. Confirmed directly by code read, not just by the investigating subagent's report. Functionally correctly scoped in every code path checked (no caller was found that omits the filter), but structurally fragile: a single future caller of the shared search client that forgets the filter would leak across every organisation with nothing else to catch it. **Not fixed in this milestone** (out of the documents-tenancy scope this milestone was given), reported per the instruction to flag anything found during the required sweep.

**Confirmed clean, no finding**: evidence exports (`GET /v1/organizations/exports/evidence`, correctly org-scoped), both AI pipelines (each LLM call operates on exactly one organisation's own content per invocation, no shared cache/vocabulary/embedding store found), and Simulator saved scenarios (organisation-scoped at both list and get, cross-org `scenario_id` 404s before any simulation logic runs).

## Confirmed legacy tables/resources lacking organisation ownership

1. **`documents`** -- zero derivable ownership (Phase 1/6). The only one in the schema.
2. **Shared Blob container + Search index** -- not a table, but a shared *resource* with app-layer-only isolation (Phase 6). Listed here because it is the same underlying class of risk the task asked this phase to hunt for, even though it isn't a database table.

No third instance of this pattern was found anywhere in the platform.

## Dependency map: what must be true before Enterprise Knowledge can safely begin

```
Enterprise Knowledge's own future schema
  -> must be organisation-scoped from its first migration (Phase 5)
  -> is independent of `documents`'s tenancy status (Phase 5 conclusion)
  -> depends on the AI Authority Builder's corpus pipeline remaining correctly
     org-scoped, which it is today (Phase 1 item 4, Phase 6)
  -> depends on the shared Blob/Search infrastructure's app-layer isolation
     continuing to be correctly applied by every future caller (Phase 6's
     MEDIUM/WARNING -- not currently broken, but structurally unguarded)

`documents` table tenancy decision (Phase 4)
  -> does NOT block Enterprise Knowledge directly (Phase 5)
  -> remains a real, disclosed defect worth resolving on its own timeline
  -> requires founder approval regardless of which option is chosen
```

## PASS / WARNING / BLOCKER matrix

| Area | Status | Evidence |
|---|---|---|
| `documents` table -- unauthenticated access | PASS | Milestone 12, re-confirmed this session |
| `documents` table -- permission gate | PASS | Milestone 12, re-confirmed this session |
| `documents` table -- per-organisation isolation | **WARNING** | Structurally impossible without a schema change; disclosed, not silently accepted |
| Historical data risk (`documents`/`authorities`) | PASS | Zero rows, live-verified this session, not merely historically claimed |
| Second FK path (`Principal.source_document_id`) | PASS (currently) | Never populated by any code; same disclosed limitation applies if it ever is |
| AI Authority Builder corpus pipeline | PASS | Confirmed genuinely separate and already org-scoped |
| Background jobs | PASS | Both cross-org-by-design jobs correctly gated; no others exist |
| SDK / frontend exposure of legacy documents | PASS | Zero consumers found |
| Shared Blob/Search infrastructure | **WARNING** | Functionally scoped today, structurally unguarded; not fixed, reported |
| Every other database model (38 of 39) | PASS | Full inventory performed; each has direct or resolvable organisation ownership |
| Exports, AI pipelines, Simulator scenarios | PASS | Confirmed clean |
| Schema/role decision for `documents` | **BLOCKER for full closure, not for Enterprise Knowledge** | Requires founder approval; does not block Enterprise Knowledge per Phase 5 |

## Enterprise Knowledge status

**Enterprise Knowledge remains NOT STARTED.** No code, schema, or architecture change was made toward it. This milestone only audited and documented; the schema options in Phase 4 were not implemented.

## Final verdict

**CONDITIONALLY READY FOR ENTERPRISE KNOWLEDGE.**

Not BLOCKED: nothing found in this milestone's audit prevents Enterprise Knowledge from beginning on its own, purpose-built, organisation-scoped foundation, and the `documents` tenancy gap is confirmed (Phase 5) not to be a dependency of that work. Not an unconditional PASS: two disclosed items remain open and require explicit approval or attention before this milestone's own scope can be considered fully closed --

1. A founder decision on `documents`' schema future (Phase 4) -- not urgent for Enterprise Knowledge specifically, but still an open, real defect.
2. The shared Blob/Search infrastructure's app-layer-only isolation (Phase 6) -- not currently broken, but worth hardening before Enterprise Knowledge potentially increases how much this shared infrastructure is relied upon.

Per instruction, this document does not authorize proceeding into Enterprise Knowledge. Awaiting explicit approval on both open items above, and on which milestone (if any) should address the Blob/Search hardening, before any further phase begins.
