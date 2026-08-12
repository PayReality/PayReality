# Milestone 1 — Security & Authorization Hardening — Implementation Summary

**Roadmap reference:** `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md` Milestone 2, items 1/4/5; `PAYREALITY_ENTERPRISE_V1_MASTER_ROADMAP.md` Security workstream, P1 items.
**Scope:** close every confirmed unscoped-read/IDOR gap named in those documents, and add the first multi-organization isolation regression tests. Explicitly out of scope (documented, not implemented — see Remaining Risks): the Operator Key org-identity decision, and Milestone 2's schema-level Runtime Policy multi-tenancy work.

## Implementation Summary

Five atomic commits, each independently buildable and re-verified against the full test suite before the next began:

1. **Evidence** (`131c5bc`) — `get_evidence`, `list_evidence`, `verify_evidence` were unauthenticated and unscoped; now permission-gated (`Permission.EVIDENCE_VIEW`) and org-scoped. Fixed the one other caller of `list_evidence` (`organization.py`'s `/exports/evidence`) for the same underlying function change. Left `GET /verification-key(s)` and `GET /chain/verify` intentionally public, per their own existing docstrings' design intent (independently verifiable by a third-party auditor with no platform credentials) — not an oversight, a deliberate distinction.
2. **Organization structure** (`17bed31`) — department/team list/create/update/delete had no organization dependency or ownership check at all; `update_business_unit`/`delete_business_unit` were missing the same check their sibling `list`/`create` already had. Added three shared, now-public helpers (`business_unit_organization_id`, `department_organization_id`, `team_organization_id`) that walk the `Team → Department → BusinessUnit → organization_id` chain once, reused everywhere rather than re-joined ad hoc.
3. **Principals** (`c9b1809`) — `list_principals` was a bare unfiltered query; `create_principal` sourced `organization_id` directly from the client request body, letting a caller create a Principal under any organization it named. Both fixed; `organization_id` now always comes from `get_current_organization`. `get_principal_authority_context` (found while fixing the above, same file) had the identical unscoped-by-ID gap and was fixed alongside it.
4. **AI Authority Builder** (`2b2782e`) — all 14 corpus-scoped read endpoints had no auth dependency and no organization filter. One shared dependency, `_authorized_corpus`, closes all 14 at once, since every sub-resource read is keyed purely by `corpus_id` with no organization column of its own.
5. **Isolation tests** (`78430cf`) — 18 new tests, the first of their kind in this codebase, using the project's own established fake-session convention (no real database available in this environment).

## Files Changed

- `server/app/routers/evidence.py`, `server/app/services/evidence_service.py`, `server/app/routers/organization.py`
- `server/app/routers/organization_structure.py`, `server/app/services/organization_structure_service.py`
- `server/app/routers/principals.py`, `server/app/services/agent_service.py`
- `server/app/routers/ai_authority_builder.py`
- `server/tests/unit/test_organization_isolation.py` (new)
- `SPECIFICATION/14_SECURITY_MODEL.md` §14.6, `SPECIFICATION/16_CURRENT_LIMITATIONS.md` §16.1

## Tests Added

18, in `test_organization_isolation.py`: 4 for Evidence, 9 for organization structure (including the three walk-helpers directly), 2 for Principals, 2 for the Authority Builder's `_authorized_corpus` dependency, 1 more for `update_business_unit`.

## Tests Passing

**282/282** (264 pre-existing + 18 new), zero regressions, re-verified after every one of the five commits above, not just at the end.

## Migration Notes

**None required.** Every table touched (`Evidence`, `AuthorityCorpus`, `Principal`, and the `BusinessUnit`/`Department`/`Team` chain) already carried the columns needed; this milestone is entirely query-filtering and dependency-injection, no schema change.

## Documentation Updated

- `SPECIFICATION/14_SECURITY_MODEL.md` §14.6's "Cross-tenant data exposure" threat-model row corrected — it previously claimed this was "N/A today," which this milestone's own investigation found to be false; the row now states precisely what was fixed and what remains.
- `SPECIFICATION/16_CURRENT_LIMITATIONS.md` §16.1's "Single-tenant routing, multi-tenant-shaped schema" entry updated from "unresolved" to "partially resolved," with the specific remaining gaps named.
- This document.

## Remaining Risks

1. **The Operator Key org-identity question is unresolved, by design.** `PAYREALITY_ENTERPRISE_HARDENING_PLAN.md` itself frames this as requiring a decision (retire vs. scope), not a mechanical fix — raising it now rather than deciding it silently inside a security-fix commit.
2. **Schema-level multi-tenancy for Runtime Policies (Milestone 2) is untouched.** The `policies` table's single-active-row-platform-wide constraint, and the complete absence of `organization_id` on `RuntimePolicyRecord`/lifecycle tables, remain exactly as found.
3. **Mutating Authority Builder endpoints** (`resolve_principal`, `resolve_relationship`, `activate_relationship`, `answer_question`, `approve_graph`) are permission-gated but do not verify their target row's organization — discovered while fixing the read endpoints in the same file, deliberately not folded in per the Scope Rule (document, don't implement). A reasonable candidate for the start of a future, narrowly-scoped follow-up.
4. **No live-database verification was possible in this environment** (no reachable Postgres, consistent with every prior phase's own disclosed limitation) — all verification is via the fake-session unit tests added, plus a clean full-suite run and a clean OpenAPI schema generation. Real end-to-end verification against a live database is recommended before this ships to any environment carrying real multi-organization traffic.

## Recommendation for Next Milestone

Proceed to **Milestone 2 — Multi-Tenant Foundation**, specifically the two items this milestone deliberately left open: (a) the Operator Key org-identity decision, and (b) the schema-level Runtime Policy multi-tenancy design (adding `organization_id` to the lifecycle tables and resolving the single-active-`policies`-row constraint). Per the roadmap's own execution order, (b) should land before any Render→Azure data migration is executed, so this is also the natural next step chronologically, not just topically.
