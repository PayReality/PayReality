# Policy Studio Architecture

Policy Studio is the workspace that sits above `RuntimePolicy` (`server/app/domain/runtime_policy/`) and Compiler V2 (`server/app/domain/compiler_v2/`), neither of which is modified by this phase. Both existed only as in-memory, unwired Python values before this phase; Policy Studio is what makes them real: persisted, reachable over the API, and operable from a browser.

## What had to be added to make this possible, named honestly

`RuntimePolicy` and `PolicyBundle` were pure dataclasses with no database table, no API route, and no caller anywhere in the application. Building a workspace on top of them required three new things, none of which touch the two protected packages:

1. **A persistence layer** (`server/app/db/models.py`'s new `RuntimePolicyRecord` table, `server/app/services/runtime_policy_service.py`), storing each `RuntimePolicy` version as a row, serialized via `schema.py`'s existing `to_dict`/`from_dict` (reused, not reimplemented).
2. **An API layer** (`server/app/routers/runtime_policies.py`), the first HTTP surface either package has ever had.
3. **A frontend** (`src/app/policy-studio/`), the first UI either package has ever had.

## Data model

One new table, `runtime_policies`, one row per **version** of a Runtime Policy (not one row per policy with mutable fields), matching `RuntimePolicy`'s own immutability (`RUNTIME_POLICY_LANGUAGE.md`: "editing one produces a new RuntimePolicy with an incremented version, never a mutation").

```
RuntimePolicyRecord
  id                  UUID, primary key, one per version (not shared across versions)
  policy_key          UUID, shared by every version of "the same policy," stable across edits
  version             int
  status              text (mirrors PolicyStatus: draft/pending_review/approved/rejected/
                       compiled/active/retired)
  content             JSONB: the full RuntimePolicy, via schema.to_dict()/from_dict()
  bundle_id           text, nullable, set once compiled
  bundle_hash         text, nullable, set once compiled
  created_at          timestamptz
```

`policy_key` is what the Policy List page groups by (one row per `policy_key`, showing its latest version); `id` is what a specific version is addressed by (diffing, rollback, deployment record). Storing the full `RuntimePolicy` as JSONB rather than exploding every field into its own column is deliberate: `RuntimePolicy`'s shape belongs to `runtime_policy/` alone, and a column-per-field mapping would silently create a second, competing definition of that shape the moment the two drift, exactly the kind of duplication Phase 1 and 2 were careful to avoid. `schema.py`'s `to_dict`/`from_dict` is the single source of truth for the on-the-wire and on-disk shape; this table just stores its output.

## Status lifecycle, enforced server-side

`PolicyStatus` already defines the exact states needed (`draft → pending_review → approved/rejected → compiled → active → retired`); this phase enforces the *transitions* between them, which didn't exist as enforced rules anywhere before:

```
draft ──submit for review──> pending_review ──approve──> approved ──compile──> compiled ──deploy──> active
  ↑                                │                                                                  │
  └──────────────(edit, new version)                     pending_review ──reject──> rejected          │
                                                                                                          │
                                                          (a later version's activation retires this one)┘
```

Enforced in `runtime_policy_service.py`, not the router: **only an `approved` policy can be compiled or deployed** ("No direct deployment from Draft" is the headline requirement; the actual rule implemented is one step earlier and stricter, a draft cannot even be compiled, let alone deployed, without passing review first). An out-of-order transition attempt is a `409`-style structured error, the same "never silently allow, never raise an unhandled exception" discipline `compiler_v2` and `runtime_policy/validators.py` already hold themselves to.

## API surface

All under `/v1/runtime-policies`, gated by the existing operator-key authentication (`server/app/security.py::verify_operator_key`) for every mutating call, exactly the same auth model every other policy-mutating endpoint already uses (`SECURITY.md`). No new auth mechanism was invented for this.

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/runtime-policies` | List, one row per `policy_key` (latest version), with search/filter/sort query params |
| GET | `/v1/runtime-policies/{policy_key}` | One policy's latest version |
| GET | `/v1/runtime-policies/{policy_key}/versions` | Full version history |
| GET | `/v1/runtime-policies/{policy_key}/versions/{version}` | One specific version |
| POST | `/v1/runtime-policies` | Create (version 1, status `draft`) |
| PUT | `/v1/runtime-policies/{policy_key}` | Edit: creates a new version, status reset to `draft` |
| POST | `/v1/runtime-policies/{policy_key}/submit-for-review` | `draft → pending_review` |
| POST | `/v1/runtime-policies/{policy_key}/approve` | `pending_review → approved` |
| POST | `/v1/runtime-policies/{policy_key}/reject` | `pending_review → rejected` |
| POST | `/v1/runtime-policies/{policy_key}/compile` | `approved → compiled`; runs Compiler V2, stores diagnostics or bundle |
| POST | `/v1/runtime-policies/{policy_key}/dry-run` | Runs Compiler V2's `dry_run` against a compiled version; never changes status |
| POST | `/v1/runtime-policies/{policy_key}/deploy` | `compiled → active`; only reachable from `compiled` |
| GET | `/v1/runtime-policies/{policy_key}/diff?from={v}&to={v}` | Structural diff between two versions |

## Diff, affected agents/policies, and risk impact: bounded and named, not oversold

Same discipline `compiler_v2`'s conflict detector already committed to (`COMPILER_V2_ARCHITECTURE.md`): named, practical, bounded checks, not a claim of complete analysis.

- **Diff**: field-by-field comparison of two `RuntimePolicy` versions' `to_dict()` output (scope, conditions, constraints, effect). Conditions are diffed by `(field, operator)` key: a condition whose `(field, operator)` pair exists in both versions but with a different value is "modified"; one only in the newer version is "added"; one only in the older is "removed."
- **Affected Agents**: every `Agent` whose `acting_for_principal_id` matches the policy's `scope.principal` (a real database query, not a heuristic), since those are exactly the agents whose behavior could change if this policy's conditions change.
- **Affected Runtime Policies**: every other `RuntimePolicyRecord` sharing the same `(scope.principal, scope.action)`, the identical grouping `compiler_v2`'s conflict detector already uses, reused rather than reinvented, since that's precisely the set this compiler would re-run conflict detection against.
- **Risk Impact**: a bounded heuristic, not a real risk model: `increased` if a numeric condition's limit was raised or a condition was removed (both make the policy strictly more permissive for some input that previously wouldn't have matched), `decreased` if a limit was lowered or a condition was added, `unchanged` otherwise. Named as a heuristic explicitly in the UI (`POLICY_STUDIO_COMPONENTS.md`), not presented as a certified risk score.

## Frontend placement

A new top-level nav section, "Policy Studio," alongside the existing workflow nav (`Overview → Authority → Policy → Runtime Decisions → Evidence → Assurance`, see `ARCHITECTURE.md`), not folded into the existing "Policy" item: the existing Policy page is the document-upload-and-review flow (today's real, live, unmodified `Authority`/`Mandate` pipeline); Policy Studio is a distinct, parallel way of getting to a compiled bundle, exactly as `AUTHORING_ARCHITECTURE.md` described the three authoring modes converging on one canonical model without collapsing into one UI.

## Deploy is real, on purpose, and here is exactly why it's safe

An earlier draft of this document assumed Deploy would have to stay sandboxed, separate from the real `payreality.authorization` OPA package `intent_service.py`'s actual decision-making traffic reads, to avoid any risk of conflicting with the existing document-upload-and-activate flow. Checked directly against `policy_service.py::activate_policy` before finalizing this: it always uploads the same fixed `REGO_TEMPLATE` string to OPA under one policy id (`"authorization"`), and swaps only `data.mandates`; a PUT to an existing OPA policy id *replaces* its content rather than conflicting with it (confirmed directly in `COMPILER_V2_ARCHITECTURE.md`'s own OPA verification work). That means Policy Studio's Deploy can safely reuse the exact same mechanism: `opa.upload_policy("authorization", bundle.rego_source)`, no separate `data.mandates` upload needed (a Compiler V2 bundle is fully self-contained Rego, unlike the old template). Whichever bundle was deployed most recently, through either path, is simply what's loaded; there is no scenario where two are loaded simultaneously and conflict.

This was confirmed with the user explicitly before implementing, since it's a real change to live production behavior, not just new code: the first policy deployed through Policy Studio starts genuinely governing real Intent evaluation on the live API.

Deploy therefore creates a real, new row in the *existing* `policies` table (no schema change needed there, reused exactly as it already exists), retires whatever was previously active exactly the way `activate_policy` already does today, and pushes the compiled bundle to the real OPA instance. This means a policy authored, reviewed, approved, compiled, and deployed entirely through Policy Studio genuinely governs real Intent evaluation, the actual, concrete demonstration of `COMPILER_V2_ARCHITECTURE.md`'s proof that the Decision Engine doesn't care where a policy came from, not a sandboxed approximation of it. `bundle_uri` on the new `Policy` row is set to a value that identifies it as Policy-Studio-originated (`runtime_policy_studio:<policy_key>:<version>`), so anyone reading the `policies` table later can tell which authoring path produced the currently active bundle.

**What was actually verified live, and what wasn't.** After deploying this phase, create, submit-for-review, approve, compile, and dry-run were all exercised end to end against the real production database and the real OPA instance, using a throwaway verification policy scoped to a fake principal, and this caught a real bug (compile crashed with a 500 because the audit trail's `created` timestamp was never stamped at creation, fixed and reverified). Deploy itself was deliberately not exercised live in that same pass: at the time, one real policy was already active in production, and running a real deploy against the throwaway test policy would have retired it and pushed a bundle containing only the fake test rule, fail-closed-denying every real Intent evaluation until manually reverted. Given that live production impact, the choice was to trust deploy_policy() on code review, since it reuses the exact same `opa.upload_policy("authorization", ...)` call and the exact same Policy-table retire-then-activate pattern `activate_policy` already runs in production today, rather than to disrupt real traffic to prove it. The first real deploy through Policy Studio remains the actual first live exercise of that code path.

## Runtime Policy Lifecycle (Phase 5, see AUTHORITY_INTELLIGENCE_PHASE5_SUMMARY.md)

Everything above (statuses, `create_policy`/`edit_policy`/`submit_for_review`/`approve`/`reject`/`compile_policy`/`deploy_policy`, the Diff engine) is unmodified by Phase 5 and remains the actual mechanism. Phase 5 adds a governance layer strictly on top: explicit rollback (a new draft copied from a prior version, tagged `rollback_of_version`, still going through the full review pipeline), scheduled activation/retirement (`PolicyActivationSchedule`, executed only by manually or externally triggering `process_due_schedules` — there is no background task runner), a Runtime Impact Preview and safety-check gate (`services/runtime_policy_safety_checks.py`) before activation, one new terminal status (`archived`), and an immutable `RuntimePolicyLifecycleEvent` audit trail that doubles as the Policy Timeline. The frontend's Publish button on `PublishPage` now calls the new safety-gated `lifecycle/activate` endpoint (which itself calls the unmodified `compile_policy`/`deploy_policy` above) rather than the old raw `/deploy` endpoint directly; `deploy_policy` and its endpoint remain available unchanged.

## What this phase deliberately does not do

- Does not modify `runtime_policy/` or `compiler_v2/` in any way; both are imported and called, never edited.
- Does not modify `policy_service.py`, `opa_client.py`, or any existing router; Policy Studio's deploy path calls their existing public functions, it does not change them.
- Does not expose Rego anywhere in the UI, including in error messages: a compile failure surfaces the `CompilerError`'s `code`/`message`/`policy_id`/`path`, never the Rego source `compiler_v2` generates internally.
