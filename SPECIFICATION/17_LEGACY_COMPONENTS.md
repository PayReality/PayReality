# Part 17 — Legacy Components

**Supersedes/synthesizes:** `PHASE_0.md` (status corrected: implemented, not proposed). This part is the authoritative record of what was retired, when, why, and — critically — the one place that legacy component's status is *not* what it first appears to be.

## 17.1 Why a legacy pipeline existed at all

PayReality originally had one policy-authoring path: upload a delegation-of-authority document → extract candidate Authorities → human review → compile into Mandates → activate a Policy (Rego bundle) → OPA. This is the **Authority/Mandate model** (`domain/compiler/compiler.py`, `services/policy_service.py`/`document_service.py`/`review_service.py`, mounted via `routers/policies.py`). A second, richer pipeline was later built alongside it — Compiler V2 / Runtime Policy Studio (`domain/compiler_v2/`, `services/runtime_policy_service.py`) — supporting a genuine condition language, agent/resource-level scoping, and three authoring surfaces (manual, AI Authority Builder, AI Policy Builder).

## 17.2 The risk this created, and the emergency stopgap

Both pipelines could independently write to the **same** OPA package (`payreality.authorization`) and the **same** "active policy" slot, with zero coordination between them — a deploy through either could silently clobber the other with no warning. This was fixed first as an emergency stopgap, confirmed live: the legacy pipeline's four write endpoints (`upload_document`, `review_authority`, `compile_policy`, `activate_policy`) were changed to immediately `raise HTTPException(status_code=410, detail=...)`, and a defense-in-depth check (`UnexpectedActiveWriterError`) was added to `deploy_policy` refusing to overwrite an active policy it didn't itself write (§17.4 explains why this check still exists even after full retirement).

## 17.3 Full retirement (this session)

Once the stopgap had been live for a period with zero incidents, and production data confirmed genuinely zero non-empty rows across `documents`/`authorities`/`mandates`/`constraints` (checked directly, not assumed), the dead code itself was removed:

| Removed | What happened to it |
|---|---|
| `domain/compiler/compiler.py` (the entire file, then the empty directory) | Deleted. `to_utc_iso`, its one still-needed export, was relocated to a new `domain/time_utils.py` first, since `intent_service.py` (live code) depended on it |
| `server/tests/unit/test_compiler.py` | Deleted (tested only the now-deleted module) |
| `services/policy_service.py` | Trimmed from ~200 lines to exactly `list_policies` |
| `services/document_service.py` | Trimmed to exactly `list_documents` |
| `services/review_service.py` | Trimmed to `KNOWN_CURRENCIES`, `AuthorityWithFlags`, `_compute_flags`, `list_authorities_for_review` |
| `Intent.requested_scope`, `Intent.metadata` columns | Dropped via migration `805e62a44ac1`, after confirming zero non-default rows in production |
| `src/app/live/pages/LiveDocuments.tsx` | Deleted — a real frontend regression discovered mid-cleanup: this page still called the newly-410'd endpoints, so its upload/review/compile/activate buttons were silently failing in production. Its route now redirects to `/governance/upload` |

**What was deliberately kept:** `Authority`/`Mandate`/`Constraint`/`Document` class definitions and their now-empty tables in `db/models.py` — the lower-risk, fully-reversible option versus a destructive schema migration, consistent with this engagement's general preference for additive/reversible changes over aggressive cleanup. `routers/policies.py` keeps its three read-only endpoints (`list_documents`, `list_authorities`, `list_policies`) live, since they have real callers and return real (if currently empty, for the first two) data.

**Update (Authority-as-a-continuous-object, Stage G):** `Authority` and `Mandate` are no longer empty or dead. A *new*, different write path, not the retired legacy pipeline above, now creates real rows: `ai_policy_builder_service._create_authority_for_candidate` at Rule promotion, and `runtime_policy_service._ensure_mandate` at Policy deploy. `Constraint` and `Document` remain genuinely dead; no new write path was added to either. See §17.4's table below and §17.5's reconciliation for the corrected status.

## 17.4 The one nuance that makes "legacy" the wrong word for `policies`

Read this carefully — it is the single most important correction in this part, and it has changed since this section was first written. Of the five legacy tables: **two are genuinely dead** (`documents`, `constraints` — confirmed zero rows in production as of this writing, no new write path since). **Two were revived** (`authorities`, `mandates`) by Authority-as-a-continuous-object (Stage G), which added a new write path unrelated to the retired legacy pipeline described above — see the update note in §17.3. The fifth, **`policies`, is not dead** either — it is live, actively written infrastructure under a new sole writer.

`domain/decision/engine.py::evaluate()` was never modified when Compiler V2 was built; it still resolves "the active policy" by querying the legacy `policies` table for `status = 'active'`. Rather than change the Decision Engine, `runtime_policy_service.deploy_policy` was built to **write into this same table on every deploy** — a new row, `bundle_uri="runtime_policy_studio:{policy_key}:{version}"`, retiring whatever was previously active there. `UnexpectedActiveWriterError` (§17.2) is the guard that survived retirement specifically because this table is still genuinely shared, load-bearing infrastructure, not a vestige: it fails loudly if the currently-active row wasn't written by `deploy_policy` itself, rather than silently overwriting a row from some writer this module doesn't recognize.

Confirmed directly against production for this specification: `policies` holds 5 rows (4 `retired`, 1 `active`), every one created since Compiler V2 became the sole writer, none by the original legacy pipeline. A reader who saw `Authority`, `Mandate`, `Constraint`, and `Document` sitting empty and reasonably concluded "the whole legacy schema cluster is inert" would be wrong about this one member of that cluster specifically — see [05_DATABASE.md](05_DATABASE.md) §5.1/§5.5, [07_RUNTIME_POLICY_ENGINE.md](07_RUNTIME_POLICY_ENGINE.md) §7.11, and [12_DECISION_ENGINE.md](12_DECISION_ENGINE.md) §12.3, the three other places this specification states this precisely because it is easy to get wrong.

## 17.5 Full active/dead reconciliation

| Component | Status |
|---|---|
| `domain/compiler/` | **Deleted** |
| `domain/extraction/` (legacy extraction providers) | **Dead** — zero callers, kept only because nothing currently forces its removal |
| `services/policy_service.py`, `document_service.py`, `review_service.py` (surviving functions) | **Active** (read-only) |
| `routers/policies.py`'s 4 write endpoints | **Retired** — always `410` |
| `routers/policies.py`'s 3 read endpoints | **Active** |
| `Authority`, `Mandate` tables | **Revived** (Stage G) — real rows created at Rule promotion and Policy deploy, via a new write path, not the retired legacy pipeline |
| `Constraint`, `Document` tables | **Dead**, kept empty, deliberately not dropped |
| `policies` table | **Active** — repurposed as the Decision Engine's active-bundle pointer, sole writer `deploy_policy` |
| `LiveDocuments.tsx` | **Deleted** |
| `governance/legacy-review` route and its 4 old aliases | **Kept as redirects only**, pointing at `/governance/upload` |

## 17.6 What this retirement demonstrates about the platform's own discipline

The sequence — stopgap first, verify zero production impact, then remove — plus the mid-cleanup discovery and fix of the `LiveDocuments.tsx` regression, plus the correct identification that `policies` needed to stay rather than be dropped alongside its four genuinely-dead siblings, is itself evidence for how this codebase's own changes get made: additive and reversible by default, verified against real production data rather than assumed, and re-checked rather than trusted once written down. The same standard this specification was asked to apply to the rest of the platform.
