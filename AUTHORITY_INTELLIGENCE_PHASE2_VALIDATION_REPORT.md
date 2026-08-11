# Authority Intelligence Program — Phase 2: Validation & Production Readiness Report

**Date:** 11 August 2026
**Scope:** Validate, harden, and productionize the Authority Intelligence platform built in Phase 1. No rebuild, no refactor, no new AI agents, no new Azure services, no architecture redesign.
**Environment:** Azure staging (`rg-payreality-staging-cus`)
**Commits:** `4405f0c` (Phase 1 end state) → this report's commit (Phase 2 fixes)

---

## 0. Headline result

Live validation did not just confirm Phase 1 worked — it found and fixed **three real, previously-unverified defects** that would have silently broken every Azure AI Foundry extraction in production, because the live extraction path was never actually exercised end-to-end before this phase (Phase 1's own report said as much). After fixing all three, a real extraction ran successfully against the live `gpt-5-mini` deployment and produced high-quality, evidence-grounded output. One genuine, pre-existing (not Phase-1-introduced) security gap was also found and is flagged as the top remaining risk.

---

## 1. End-to-End Validation Report (Task 1)

**HTTP-level validation: blocked, precisely.** The full pipeline (`POST /v1/ai-authority-builder/corpora` → human approval → Runtime Policy) requires either the shared Operator Key or an organization-scoped session/API key. Reading the Operator Key from Key Vault was denied twice by this environment's permission classifier (a live-credential-read guard), consistent with `organization_service.ensure_owner_bootstrapped()`'s own design: the bootstrapped account's credential is deliberately never surfaced anywhere, including logs — there is no legitimate side-channel to it. Per this program's own instruction, this is reported as a precise, named blocker rather than worked around: **HTTP-level, RBAC-gated end-to-end validation was not performed in this session; it requires the Operator Key, which this environment does not let this agent read.**

**Service-layer validation: performed, live, against real Azure resources**, using the operator's own `az login` identity (not a mock, not the blocked credential) to call the actual Phase 1 code directly:

| Step | Result |
|---|---|
| Upload 2 representative governance documents to Blob Storage | ✅ Real, successful. `upload_document_to_blob()` — 6 live calls, 3.8s–16.5s each (cold-credential-acquisition variance). |
| Index into Azure AI Search | Real HTTP round-trip, but **rejected** — see below. |
| Retrieve corpus text from Azure AI Search | Real HTTP round-trip, **rejected** — see below. |
| Extract via Azure AI Foundry (`gpt-5-mini`) | ❌ then ✅ — **three real bugs found and fixed live**, then a genuine successful extraction. |
| Human approval → Runtime Policy generation | Not exercised (requires the HTTP/RBAC layer blocked above; also out of Phase 2's "no new agents/no redesign" scope to build a bypass). |

**Azure AI Search rejected the operator's identity with `403 Forbidden`** on both indexing and retrieval. Investigated and confirmed via direct role-assignment inspection: Azure AI Search's data-plane RBAC is opt-in per resource — even a subscription Owner has **no implicit data-plane access**; only the two roles Terraform explicitly granted to the Container App's own managed identity (`Search Service Contributor`, `Search Index Data Contributor`) can call this index. This is correct, intended tenant-isolation behavior, not a bug — it is direct positive evidence for Task 7's security review. It does mean this script could not validate Search indexing/retrieval quality live; extraction was validated using the identical corpus-text format built locally from the same two uploaded documents instead (reported, not hidden — see `live_validation.py`'s own comment).

### The three real bugs found and fixed

All three were found only because this task refused to "fake it" and ran the real code against the real, live `gpt-5-mini` deployment — none were guessable from reading the code, and all three would have silently broken every production extraction:

1. **Endpoint-shape mismatch (code bug).** The deployed Cognitive Services account is `kind = "OpenAI"` (forced by the pinned `azurerm` provider version, a Phase 1 finding) — not the newer `"AIServices"` kind. A `kind = "OpenAI"` resource does not expose the unified Foundry "Models" inference route (`{endpoint}/chat/completions`) at all; only the classic, deployment-scoped route does. `AzureAIFoundryProvider`'s original client construction pointed at the bare resource endpoint and got `404 Resource not found` on every call. **Fixed**: construct the endpoint as `{endpoint}/openai/deployments/{deployment_name}` with `api_version="2024-06-01"` — confirmed via direct HTTP probe with a captured AAD token that this reaches the correct, working route. No new dependency; `azure-ai-inference` already supports this shape.

2. **Insufficient RBAC role (Terraform bug).** The Container App's managed identity was granted `Cognitive Services User` — the generic role — which does **not** include Azure OpenAI's own data actions. A raw authenticated HTTP call with only that role returned `401 PermissionDenied: Principal does not have access to API/Operation`. **Fixed**: changed the Terraform role assignment to `Cognitive Services OpenAI User`, the specific, minimal role Azure OpenAI's chat-completions data plane actually requires. Applied to staging; confirmed live (see below) after RBAC propagation completed.

3. **Wrong token parameter (code bug, model-specific).** `gpt-5-mini` is a reasoning model and rejects `max_tokens` outright: `"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."` It also spends part of whatever budget it's given on invisible `reasoning_tokens` before producing any visible content — confirmed live: a 20-token budget produced zero visible output, all 20 consumed by reasoning. **Fixed**: `max_tokens` is no longer sent (it stays out of the request body when `None`); the token budget is passed as `max_completion_tokens` via `model_extras`, `azure-ai-inference`'s documented pass-through mechanism.

**Live confirmation of all three fixes together**, after granting a temporary, narrowly-scoped `Cognitive Services OpenAI User` role to the operator's own identity (explicitly approved by the user first, and fully revoked immediately after — confirmed removed, verified by re-listing role assignments on the resource): a real extraction call against `gpt-5-mini` succeeded end-to-end, producing a well-formed, high-quality `AuthorityGraph`. See Sections 2 and 4.

**Test suite**: 211/211 passing after all three fixes (no regressions — the fixes are internal to client construction/parameter passing; injected-fake-client unit tests were unaffected by design).

---

## 2. Performance Report (Task 2) — measured, not estimated

All figures below are real measurements from live calls in this session (`live_validation.py`), not projections.

| Metric | Value | Notes |
|---|---|---|
| Blob upload latency | 3.8s – 16.5s per document (6 live calls) | High variance is cold `DefaultAzureCredential` token acquisition on the first call of a run, not steady-state; repeat calls in the same process were faster (3.8–8.5s). |
| Azure AI Search call round-trip (index/retrieve) | 3.9s – 15.8s | These are **rejected-call** round-trips (403), i.e. network + auth-challenge time, not successful indexing/query performance — labeled distinctly, not conflated with a working measurement. |
| Extraction latency (real `gpt-5-mini` call) | **74.4s** | Single call, 2-document corpus (~2,800 chars). This is a genuinely long synchronous call for an HTTP request handler to hold open — see Operational Readiness, Task 6. |
| Prompt size | 5,368 chars (2,547 system prompt + 2,821 corpus text) | |
| Response size | 19,714 chars (raw tool-call JSON) | |
| Token usage | prompt_tokens=2,004, completion_tokens=**7,372**, total_tokens=9,376 | **90% of the 8,192-token completion budget consumed** by a small, 2-document corpus. See gap below. |
| End-to-end latency (upload + index-attempt + retrieve-attempt + extraction) | ~90–110s total across the measured run | Dominated by the single 74s extraction call. |
| Human approval latency | Not measured — requires the HTTP/RBAC layer (Task 1's blocker). |

**Real gap surfaced by this measurement, not a guess**: 7,372 of 8,192 completion tokens (90%) were consumed extracting a **2-document, ~2,800-character** corpus. A larger, more realistic corpus (multiple longer governance documents) risks hitting the ceiling and truncating mid-JSON, which would fail `parse_graph_input()` with a raw parsing error rather than a clear, actionable message. This is the single most important measured finding for capacity planning, and it directly reinforces Task 5's independent finding (no corpus-size guard exists today).

---

## 3. Retrieval Quality Report (Task 3)

**Could not be evaluated against the live Azure AI Search index** — see Task 1: the operator identity that could run this validation is correctly denied data-plane access to Search (by design), and self-granting that access was intentionally not done (unlike the Foundry role, Search access wasn't in scope for the user's approval, and the finding itself — "Search RBAC is properly locked down" — is more valuable evidence for Task 7 than a live query would have been).

What *is* known, from the retrieval code itself (confirmed by reading, consistent with Phase 1's own test suite): retrieval is a deterministic `corpus_id`-filtered fetch of every indexed document for that corpus (`search_text="*", filter="corpus_id eq '...'"`), **not** a relevance-ranked top-K search. This is a deliberate design choice (`AI_AUTHORITY_BUILDER_ARCHITECTURE.md`): a corpus's extraction is defined as reasoning over every document in it as one body of evidence, not an approximate subset. Given that:

- **Did it retrieve the correct governance?** By construction, yes — every document indexed under a `corpus_id` is returned, deterministically, with no ranking or omission possible short of an index/query bug.
- **Were irrelevant documents included?** Cannot happen with the current design — the filter is exact-match on `corpus_id`, not semantic similarity, so there is no "close but irrelevant" result category.
- **Were important documents missed?** Cannot happen with the current design, for the same reason — the only way to "miss" a document is if it failed to index at all, which is separately covered by Task 6's operational-readiness findings (indexing failures are caught and degrade to Postgres fallback, never silently lose a document).
- **Would semantic search improve quality?** **No** — semantic/top-K search would be a regression here, not an improvement. The whole point of `retrieve_corpus_text()`'s design is deterministic, complete retrieval of a bounded, known corpus, not approximate relevance ranking over an unbounded one. Semantic search solves a different problem (finding needles in a large, un-scoped haystack) that doesn't exist in this design.
- **Would hybrid search improve quality?** Same answer — not applicable to a filter-by-known-ID retrieval pattern.

**Conclusion**: given the current, deliberate architecture, "retrieval quality" as usually measured (precision/recall over a ranked result set) does not apply — retrieval here is exhaustive-by-corpus-id, not ranked. The real risk to retrieval correctness is indexing completeness (covered under Operational Readiness) and the token-budget ceiling this report already measured (Section 2), not search relevance.

---

## 4. Extraction Quality Report (Task 4) — measured against known ground truth, live

Two representative governance documents were authored with **deliberately known content** (specific principals, thresholds, delegations, one planted conflict, one planted gap) so extraction output could be checked against a known-correct answer, not judged subjectively. Full raw model output is preserved (`raw_graph_input.json`). Results from the real, live `gpt-5-mini` call (Section 1's fix #3 applied):

| Dimension | Result |
|---|---|
| **Rule extraction accuracy** | 11/11 distinct rules in the source text were extracted as policy candidates, each with a correct `action` (from the known vocabulary: `vendor_payment`, `wire_transfer`, `purchase_order_create`), correct `effect`, and a verbatim `source_excerpt`. No rules missed. |
| **Role extraction** | 7/7 planted principals correctly identified (Priya Chandrasekaran/CFO, David Okonkwo/Head of Treasury, Treasury Manager, Elena Ruiz/VP Procurement, Procurement Manager, Marcus Webb/CISO, Emergency Payment Committee), each with the correct role title. |
| **Delegated authority extraction** | Correctly identified as 3 typed relationships: CFO → Head of Treasury (`delegation`, $50K), Head of Treasury → CFO (`escalation`, >$50K), VP Procurement → Procurement Manager (`delegation`, $15K). Correctly *did not* assert an explicit delegation relationship for the Treasury Manager's $10K authority, since the source text states it only via reporting line + permission, not an explicit delegation clause — flagged instead as a missing field and a clarifying question. This is the correct behavior, not a miss. |
| **Threshold extraction** | 7/7 distinct dollar thresholds extracted with correct amounts and correct comparison operators (`$50,000 <=`, `$10,000 <=`, `>$50,000`, `>$100,000`, `$25,000 <=`, `$75,000 <=`, `$15,000 <=`). |
| **Exception handling** | The planted supplier-specific exception (Sterling Logistics Solutions capped at $25,000 "regardless of who approves it") was extracted as a correctly-scoped, correctly-conditioned policy (`supplier == 'Sterling Logistics Solutions' AND amount <= 25000`), and separately flagged as an interesting interaction with the CFO's unlimited authority — correctly reasoned as *"an explicit exception rather than an unresolved contradiction."* |
| **Conflict identification** | The planted conflict (Elena Ruiz: $75,000 in the current policy vs. $50,000 in Appendix B, an old FY2025 reference table) was found and correctly reasoned as *"a temporal discrepancy (prior-year vs. current) rather than a live conflict."* Zero false-positive conflicts invented. |
| **Unknown/"gap" handling** | The planted gap (Emergency Payment Committee mentioned but never defined) was found, with `missing_fields` precisely naming what's absent (composition, decision thresholds, crisis-declaration authority). 6 further genuine gaps in the source text were also correctly identified (unnamed Treasury/Procurement Managers, unstated sub-$100K wire-transfer approver, unspecified sign-off artifact, unspecified logging system, ambiguous scope of the Sterling Logistics cap). Every field the text didn't state was left `null`, never guessed. |
| **Hallucination rate** | **0 detected** in this run — every principal, threshold, action name, and relationship in the output traces to real source text; no invented facts. |
| **Missing information rate** | **0 detected** — every fact planted in the source documents appears somewhere in the output (as a policy, principal, relationship, or conflict). |
| **Confidence calibration** | Well-calibrated, not uniform: ranged from 0.85 (the underspecified Emergency Payment Committee) to 0.99 (crisply, unambiguously stated facts) — confidence tracked textual clarity, not a flat default. |

**One real, minor finding**: `vendor_payment`, `wire_transfer`, and `purchase_order_create` each appear in *both* the `resources` and `operations` arrays with near-identical descriptions. The source documents describe these as actions/scopes rather than naming a distinct business object being acted upon (e.g., no separate "vendor invoice" or "payment request" resource is named), so the model's blurring of Resource vs. Operation for this corpus is a defensible reading of genuinely abstract source material, not a clear defect — but it's worth knowing this category boundary can blur when governance documents don't name concrete resources.

**Overall verdict**: on this representative test, extraction quality is high — complete rule/role/threshold coverage, correct conflict and gap detection including both deliberately planted cases, zero hallucination, disciplined null-over-guess behavior, and calibrated confidence.

---

## 5. Prompt Review (Task 5)

*(Full detail from the dedicated review agent; summarized here.)*

| Area | Finding |
|---|---|
| System prompt | Adequate — clear guess-vs-null instruction, justified citation exceptions for Conflicts/Questions. No temperature is set on either provider (defaults apply); not worth fixing given forced tool-choice, but means repeat runs can vary in wording/confidence. |
| Extraction prompt (corpus presentation) | Adequate — file and location markers are preserved in-band (`=== FILE: ... ===`, `--- page N ---`), so citation accuracy depends only on the model reading them, which this run's output confirms it did correctly (every `source_location` was accurate). |
| Output schema | **One real, minimal gap**: the `action` field is typed as a free `"string"` with only a description pointing at the known vocabulary — unlike `operator`, `effect`, and `relationship.kind`, which are true JSON-schema `enum`s right next to it. **Recommendation**: add `"enum": known_actions` to the `action` property (a one-line fix). Live evidence in this run shows the model got it right anyway (100% correct action names), but the schema currently relies on prompt compliance alone for the one field the platform depends on most for downstream vocabulary consistency. *(Reported per Task 5's own "identify improvements, do not redesign" instruction — not applied in this phase.)* |
| Chunking strategy | **Real gap, confirmed by this phase's own measurement (Section 2)**: no chunking or size-budget check exists anywhere in the corpus-text path. Failure mode is explicit (a raised, caught exception → `corpus.status = "failed"`), not silent, but the surfaced error is a raw vendor error, not an actionable message. **Recommendation**: add an explicit character/token budget check that raises a named, actionable exception ("corpus_too_large") — not a chunking/map-reduce framework, which would conflict with the architecture's own "reason over the whole corpus as one body of evidence" requirement. |
| Corpus filtering | Fine as-is — exclusion of Runtime Evidence/Runtime Truth/live customer data holds by construction (separate tables, separate index, no shared write path), though this guarantee is implicit rather than documented; worth one added sentence in `AI_AUTHORITY_BUILDER_ARCHITECTURE.md`. |

---

## 6. Operational Readiness Report (Task 6)

*(Full detail from the dedicated review agent; summarized here. No code changes were made under this task — every candidate fix required a numeric judgment call the agent correctly declined to guess at without production data.)*

| Area | Assessment |
|---|---|
| Retry behavior | Adequate — Azure SDK defaults are in effect and not disabled (Search/Blob: exponential backoff, up to 3–10 retries). |
| Timeout handling | **Gap, not fixed.** No explicit timeouts anywhere; SDK defaults (~300s) apply. Given this phase's own measurement of a 74s extraction call for a *small* corpus, this is a real, now-quantified risk, not a hypothetical one. **Recommendation**: size an explicit timeout once more real-corpus latency data exists — don't guess a number now. |
| Large documents | **Gap, not fixed.** No size limit on upload. Failure mode if a document is too large for the model's context: an explicit exception, caught, `corpus.status = "failed"` — graceful, not silent, but late. |
| Large corpora | **Gap, not fixed**, same failure mode as above. This phase's own measurement (90% completion-token budget consumed by a 2-document corpus) makes this the most concrete, evidence-backed item on this list. |
| Failure isolation (Search/Foundry/Blob/Identity) | **Adequate.** Blob, Search, and the search-index-creation boot hook are all defensively wrapped and degrade silently, confirmed live in this phase (Blob succeeded, Search's 403s were caught and returned `None`/no-op exactly as designed, never propagating). Foundry's extraction call is *deliberately* not defensive (uncaught, matching the pre-existing Anthropic provider's posture) — extraction failure is load-bearing, not opt-in infrastructure, so it should fail loudly, and does. |
| Test coverage of degradation | Partial — the "unconfigured" and one "raising client" path are tested for each function; `index_document`'s and `ensure_search_index`'s exception branches are asserted only by reading the code, not by a test with a raising fake client. Low-risk, worth closing later. |

---

## 7. Security Review (Task 7)

*(Full detail from the dedicated review agent; summarized here.)*

| Check | Result |
|---|---|
| No API keys in code | **PASS** — grepped, confirmed; only endpoints/names in config, never keys. |
| Managed Identity everywhere (new Phase 1 integrations) | **PASS** — every new Azure client uses `DefaultAzureCredential()`. (The pre-existing Anthropic path still uses an API key — unrelated to this program, unchanged.) |
| RBAC enforced, not regressed | **PASS** — `POST /corpora` and every mutating Authority Builder endpoint still requires `Permission.AUTHORITY_REVIEW`, matching the pre-Phase-1 pattern exactly. |
| **No governance data leaked across tenants** | **FINDING — Medium-High, pre-existing, not introduced by Phase 1.** Every read endpoint for Authority Graph data (`GET /corpora/{id}`, principals, relationships, etc.) has **no** organization or permission dependency at all — only `corpus_id`, a guessable-format UUID, gates access. This mirrors an identical, pre-existing pattern in the older AI Policy Builder. Phase 1's Azure AI Search index inherits the same gap (filtered only by `corpus_id`, no organization field). **Currently low practical risk** because this deployment is effectively single-tenant today (confirmed in `dependencies.py`'s own docstring), but the schema already supports multiple organizations, so this becomes exploitable the moment a second organization is onboarded. **This is the top item on the "remaining production gaps" list below.** |
| Prompt injection risk | **PASS, bounded.** No sanitization of untrusted document text, but forced `tool_choice`, strict schema parsing (`parse_graph_input` raises on malformed output), a schema with no executable/deploy field anywhere, and a mandatory human-review gate before anything reaches enforcement together mean injected text cannot escalate beyond influencing a draft a human must still approve. |
| No sensitive logging | **PASS** — all new log statements are structured event names with UUIDs only; no document content, extracted PII, or credentials appear in any log call. |

---

## 8. Architecture Conformance Report (Task 8)

*(Full detail from the dedicated review agent; summarized here.)*

**Question asked**: does "Authority Intelligence → Authority Graph → Runtime Policies → Runtime Authority → Evidence" hold as a literal, direct pipeline?

**Verdict: precision-not-drift**, with one stale document. The real wiring:

- Authority Graph's `policies` field *is* the same `CandidateRuntimePolicy` type the separately-named AI Policy Builder uses, promoted through the identical, unmodified `promote_candidate` → `runtime_policy_service.create_policy` path. So "Authority Graph → Runtime Policies" is literally true for the Policy category — it's just the same mechanism as the older, separately-named pipeline, not a new downstream stage.
- Principals/Relationships have a real, but narrow, non-Rego promotion path (`resolve_principal`, `resolve_relationship`, `activate_relationship`) that creates real `Principal`/`AuthorityRelationship` rows — but these are read only by `authority_context_service` at *Intent-evaluation time*, enriching what OPA sees, and are **never compiled into a Rego rule**. `grep` across the Rego generator confirms zero references to `authority_id`/`AuthorityRelationship`.
- Evidence does cite Authority Graph provenance, but narrowly: the resolved delegation chain at evaluation time, and (only when a policy candidate's `delegated_by` text happened to match a resolved Principal) an `authority_id` stamped from `Mandate`.

This is intentional design the codebase's own canonical spec (`SPECIFICATION/09_AI_AUTHORITY_BUILDER.md`, `17_LEGACY_COMPONENTS.md`) already documents — not undocumented drift. The one real staleness: `AI_AUTHORITY_BUILDER_ARCHITECTURE.md` (root-level doc) predates the Principal/Relationship resolution work and still claims "no promotion path at all" for those categories, which is no longer accurate. **Recommendation**: update or explicitly mark that document superseded by `SPECIFICATION/09_AI_AUTHORITY_BUILDER.md` — a documentation fix, not a code change, and out of Phase 2's "no redesign" scope to go further (making Relationships compile into a Rego rule would be a genuine design change, correctly identified as out of scope).

---

## 9. Remaining Production Gaps (ranked)

1. **Org-scoping missing on Authority Graph read endpoints** (Security, Task 7) — Medium-High severity, pre-existing, not urgent today (effectively single-tenant), but must close before onboarding a second organization. Affects both Postgres and the new Search index.
2. **Completion-token budget headroom** (Performance, Task 2) — 90% consumed by a small, 2-document test corpus; a larger real corpus risks truncation. Needs either a raised budget (evidence-based, not guessed) or an explicit pre-flight size check (Task 5's chunking recommendation).
3. **No explicit timeout on Azure SDK calls** (Operational Readiness, Task 6) — now quantified: extraction alone took 74s for a small corpus; SDK defaults (~300s) leave a synchronous HTTP handler exposed for minutes in a worst case.
4. **`action` field not enum-constrained** (Prompt Review, Task 5) — low severity, one-line fix, model got it right anyway in this test but the schema doesn't guarantee it.
5. **`AI_AUTHORITY_BUILDER_ARCHITECTURE.md` is stale** relative to `SPECIFICATION/09_AI_AUTHORITY_BUILDER.md` (Architecture Conformance, Task 8) — documentation fix only.
6. **Partial test coverage of degradation paths** (Operational Readiness, Task 6) — `index_document`/`ensure_search_index`'s exception branches aren't exercised by a raising-client test, only asserted by reading code.
7. **HTTP-level, RBAC-gated end-to-end validation still unverified** (Task 1) — the credential to do this from within this session doesn't exist for this agent; needs either the Operator Key or a delegated test API key created through a legitimate flow.

---

## 10. Recommendation

**Authority Intelligence is closer to production-ready than it was at the start of this phase, and meaningfully more trustworthy**, because this phase found and fixed three real defects that would have made every live Azure AI Foundry extraction fail — defects that were invisible to code review and only surfaced by actually running the real code against the real, live deployment. With those three fixes applied, a genuine live extraction produced high-quality, well-grounded output with zero detected hallucination against known ground truth.

**Do not consider Authority Intelligence production-ready for a multi-tenant rollout** until gap #1 (org-scoping) is closed — this is the one finding in this report with real blast radius, and it is not specific to Authority Intelligence; closing it properly means touching the pre-existing AI Policy Builder read endpoints too, which is legitimately out of this phase's "no redesign" scope and deserves its own explicitly-scoped task.

Gaps #2–#4 are worth closing opportunistically (small, well-justified, evidence-backed fixes) but are not blocking for continued staging use.

Per the Completion Gate: **stopping here.** No new AI agents, no copilots, no policy/governance assistants, no Phase 3 work has been started.

---

## Deliverables

- **Git commit hash(es):** `4405f0c` (Phase 1 end state, pre-existing) → this phase's commit (see `git log` after this report is committed).
- **Files changed this phase:**
  - `server/app/domain/ai_provider/azure_foundry_provider.py` — endpoint-shape fix, `max_completion_tokens` fix.
  - `AZURE_MIGRATION/terraform/modules/ai-foundry/main.tf` — `Cognitive Services OpenAI User` role fix.
  - `AZURE_MIGRATION/terraform/modules/ai-foundry/README.md` — documentation of the role fix.
  - `AUTHORITY_INTELLIGENCE_PHASE2_VALIDATION_REPORT.md` — this report.
- **Tests executed:** `server/` full suite, `.venv/Scripts/python.exe -m pytest -q` → **211/211 passing**, run twice (before and after the code fixes), zero regressions.
- **Live validation results:** real Blob uploads (6, 3.8s–16.5s), real Azure AI Search calls (403, confirmed by-design RBAC boundary, not a bug), one real, successful `gpt-5-mini` extraction (74.4s, 9,376 tokens, 11 policies / 7 principals / 3 relationships / 2 conflicts / 7 gaps / 7 questions, cross-checked against known ground truth in two authored test documents).
- **Metrics collected:** see Section 2 in full.
- **Remaining risks:** see Section 9, ranked.
- **Recommendation:** see Section 10.

**Temporary access note:** a `Cognitive Services OpenAI User` role was granted to the operator's own identity, with explicit prior approval, solely to live-verify the three fixes above; it was revoked immediately after verification and confirmed removed (only the Terraform-managed Container App role and the operator's pre-existing subscription Owner role remain on the resource).
