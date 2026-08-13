# AI Pipeline Consolidation Review

**Status: review complete. One migration implemented (AI Policy Builder onto Azure AI Foundry). One dead pipeline deleted (domain/extraction). One deeper, product-level consolidation identified and recommended, deliberately not executed here.**

This document answers Milestone 6's architecture question directly: does PayReality have one canonical AI ingestion pipeline, and if not, should it. Every claim below is grounded in the actual code read for this review, not inferred from documentation.

## What actually exists today

Four AI-related extraction code paths were found in this repository. Three are real; one is dead.

### 1. `domain/extraction/` (deleted this milestone)

A `CandidateAuthority`-producing provider hierarchy (`provider.py`, `claude_provider.py`, `fake_provider.py`), written in this project's very first commit, intended to back the original Authority/Mandate document pipeline (`routers/policies.py`'s `upload_document` and friends). That pipeline was independently retired via `PHASE_0.md`, before this engagement's own milestone numbering began, for an unrelated reason (two uncoordinated writers to the same OPA package). `SPECIFICATION/17_LEGACY_COMPONENTS.md` had already recorded `domain/extraction/` as "Dead, zero callers, kept only because nothing currently forces its removal." A repository-wide search confirmed this directly: no router, service, or test anywhere imports it. This milestone's own consolidation question is exactly the forcing function that document was waiting for, so the module has been deleted outright, not just re-flagged.

### 2. AI Policy Builder

Single document in, `CandidateRuntimePolicy` candidates out. Stores the uploaded document's raw bytes directly in Postgres (`PolicyExtractionUpload.content`, a `LargeBinary` column), never Blob Storage. Before this milestone, its only real AI provider was Anthropic's Claude, gated behind `ANTHROPIC_API_KEY`, which Milestone 5 confirmed live and directly is an invalid placeholder (a real upload attempt returned Anthropic's own `401 invalid x-api-key`). No Azure AI Foundry code path existed for it at all.

### 3. AI Authority Builder

Multi-document corpus in, a full `AuthorityGraph` out: principals, resources, operations, relationships, conflicts, gaps, questions, and, as one of those eight categories, `policies`, using the exact same `CandidateRuntimePolicy` dataclass AI Policy Builder produces (imported directly from `domain/ai_policy_builder/provider.py`, not a separate type). Every entity carries four additional Explainability Model fields (`clause_reference`, `extraction_reasoning`, `detected_assumptions`, `ambiguity_flags`) that AI Policy Builder's candidates never populate. Stores documents in Azure Blob Storage, organization-scoped (`authority-corpora/<org>/<corpus>/<doc>`), and indexes retrievable text in Azure AI Search. Has had a genuine, working Azure AI Foundry provider since the Authority Intelligence Program's own Phase 1, confirmed live and functioning end to end in Milestone 5.

### 4. Authority Intelligence (`authority_intelligence_service.py`)

Not itself a fourth extraction pipeline. This is the shared infrastructure layer, Blob upload and retrieval, Azure AI Search indexing, that Authority Builder's corpus mechanism is built on. AI Policy Builder never calls into this layer at all, which is the direct cause of the Blob-versus-Postgres storage split named above.

## The actual duplication, itemized

**Duplicated providers.** Before this milestone: two independent Claude-backed and Fake-backed provider hierarchies (`domain/ai_policy_builder/*` and `domain/ai_authority_builder/*`), structurally parallel, never sharing code, and only one of the two also had an Azure AI Foundry implementation.

**Duplicated prompts and schemas.** AI Policy Builder's own system prompt and JSON schema (previously inline in `claude_provider.py`, now `domain/ai_policy_builder/extraction_shared.py`) and Authority Builder's `policies` category within its own schema (`domain/ai_authority_builder/extraction_shared.py`) ask for the same fields (name, principal, action, resource, conditions, constraints, effect, metadata) in separately authored, near-identical wording. They are not literally shared code; they are two hand-written descriptions of the same shape, with Authority Builder's the strictly richer of the two.

**Duplicated document storage.** Postgres `LargeBinary` (Policy Builder) versus Azure Blob Storage (Authority Builder) for what is, at the point of upload, the same kind of artifact: one governance document a human is about to have AI read.

**Not duplicated.** Authority Builder's principal, resource, operation, relationship, conflict, gap, and question extraction has no Policy Builder equivalent at all; this is genuinely distinct, richer capability that a merge must not lose. Azure AI Search indexing and retrieval likewise has no Policy Builder equivalent, since a single document has nothing to search across.

## Why AI Policy Builder still depended on Anthropic

Simply put: nobody had ever written an Azure AI Foundry adapter for it. The underlying seam that would have made this cheap already existed, `domain/ai_provider/interface.py`'s vendor-neutral `AIProvider.generate_structured(...)` protocol, with a working `AzureAIFoundryProvider` implementation authenticated via Managed Identity, no API key of any kind. Authority Builder had already adopted this seam in the Authority Intelligence Program's Phase 1. AI Policy Builder, built to a similar but separately-maintained pattern, simply never got the equivalent adapter. This was not a deliberate architectural choice to depend on Anthropic specifically; it was an omission.

## Decision: migrate, implemented this milestone

**AI Policy Builder is now fully migrated onto the Azure AI Foundry architecture**, the first of the two completion-criteria options, not the retirement option, for a specific reason: its functionality is largely a subset of what Authority Builder already does well, but a full structural retirement (removing its own API surface, its own database tables, and rerouting every caller through the corpus model) is a real product and frontend change, not a blocker fix, and is explicitly out of scope for a milestone whose own charter states "this is not a feature milestone... it exists solely to eliminate the blockers." Migrating the provider is scoped, safe, reuses proven code, and closes the actual, live BLOCKER (a real, confirmed-broken call against an invalid credential) completely.

What changed, concretely:

- `domain/ai_policy_builder/extraction_shared.py` (new): the system prompt, JSON schema, and result parsing extracted out of `claude_provider.py`, mirroring `domain/ai_authority_builder/extraction_shared.py`'s own already-established split exactly, so a second provider never duplicates ~150 lines of prompt/schema/parsing logic that must stay identical across both.
- `domain/ai_policy_builder/azure_foundry_provider.py` (new): a thin adapter, structurally identical to `domain/ai_authority_builder/azure_foundry_provider.py`, wrapping the same shared `AzureAIFoundryProvider` client both pipelines now use.
- `domain/ai_policy_builder/claude_provider.py` (trimmed): now just "call Claude," using the shared prompt/schema/parsing, unchanged in what it asks the model or how it authenticates.
- `routers/ai_policy_builder.py::_provider()`: now checks `azure_ai_foundry_endpoint` first, `anthropic_api_key` second, the fake provider last, the exact ordering `routers/ai_authority_builder.py` already uses. Claude is kept as a fallback for a local or development environment with no Foundry endpoint configured, not removed; the platform still has zero hard dependency on any one vendor.
- `routers/ai_policy_builder.py`'s `/status` endpoint: now reports `ai_enabled` truthfully against whichever provider would actually be selected, matching Authority Builder's own status check, instead of only ever checking the Anthropic key.
- New unit tests (`test_azure_foundry_policy_builder_provider.py`): the same contract, cross-provider-consistency, and no-Rego-field checks already proven for Authority Builder's own Foundry provider, plus a direct test of `_provider()`'s selection order.

Azure AI Foundry is now the one canonical AI provider underlying both pipelines. Neither pipeline has any remaining hard dependency on Anthropic; both fail over to it only in an environment that has no Foundry endpoint configured at all.

## Whether duplicate functionality exists: yes, and what to do about it

The honest answer is that AI Policy Builder's entire value proposition, upload a document and get RuntimePolicy candidates, is already produced by Authority Builder's corpus pipeline as one of its eight output categories, with strictly richer output (the Explainability fields) and a real Blob/Search-backed storage model Policy Builder never adopted. The two pipelines are not equally-important siblings; one is a narrower, older special case of the other.

**Recommendation for the long-term architecture, not executed in this milestone:** retire AI Policy Builder as an independently-branded pipeline in a future, explicitly product-scoped milestone, converging on Authority Builder's corpus mechanism as the one ingestion path. Two concrete shapes this could take, in increasing order of user-facing change:

1. **Internal-only convergence.** Keep the existing `/v1/ai-policy-builder/*` API surface and its simpler single-document UX exactly as users see it today, but change what happens underneath: `create_upload` creates a single-document `AuthorityCorpus` instead of a `PolicyExtractionUpload` row, storing to Blob like every other corpus document, and extraction calls Authority Builder's own `extraction_shared.py`, filtering the returned `AuthorityGraph` down to just its `policies` category before handing candidates back in Policy Builder's existing response shape. No frontend change, no breaking API change, and the prompt/schema duplication named above disappears entirely because there would only be one prompt left.
2. **Full user-facing merge.** Retire the separate Policy Builder screens and route everything through Authority Builder's own corpus upload and review flow, presenting "just the policies" as one filtered view of a richer, already-existing result. A bigger frontend change, but the more honest end state, since it stops presenting two different tools for what is functionally one capability.

Either direction should keep `PolicyExtractionCandidate`'s existing `upload_id`/`corpus_id` dual-parent resolution (already built, already correct) rather than inventing a new join path, and should be scoped and executed as its own milestone with its own frontend verification, not folded into a blocker-resolution pass.

## Recommended long-term architecture, summarized

One extraction backend (Azure AI Foundry via `domain/ai_provider`, achieved this milestone for both pipelines). One document-storage backend (Azure Blob Storage via Authority Intelligence's own service, not yet achieved for Policy Builder, recommended above as future work). One prompt/schema per output shape, shared via an `extraction_shared.py`-style module per pipeline until the deeper merge above happens, at which point Policy Builder's own prompt file becomes unnecessary entirely. Authority Builder's richer Explainability Model and multi-entity extraction remain the superset every future ingestion surface should build on, not a parallel capability to keep re-implementing.
