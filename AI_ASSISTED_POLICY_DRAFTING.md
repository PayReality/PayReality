# Draft with AI: Architecture

## What this is

A conversational assistant inside Policy Studio's existing Manual builder (`PolicyWorkspacePage.tsx`), added in Product Experience V3.2. It is not a fourth authoring path alongside the Guided Wizard, Manual Policy Studio, and AI Policy Builder described in `AUTHORING_ARCHITECTURE.md` and `AI_POLICY_BUILDER_ARCHITECTURE.md` -- it is a way to fill in the Manual builder's own form fields faster, using the same `RuntimePolicyRequest` shape, the same validation, the same Save/review/approve/publish lifecycle, all completely unmodified.

## The one governing rule

**AI interprets and proposes; humans establish authority.** Every design choice below exists to make that structural, not just prompted:

- The assistant has no code path to Save, Submit for review, Approve, Compile, or Deploy. `server/app/routers/policy_drafting.py` exposes exactly two endpoints, `POST /v1/policy-drafting/draft` and `POST /v1/policy-drafting/explain`, and neither imports or calls anything in `runtime_policy_service.py`, `runtime_policy_lifecycle.py`, or the OPA client.
- A proposal never reaches the manual form automatically. `DraftWithAIPanel.tsx` renders a diff (`DiffPreview`) and an explicit "Apply proposal" button; nothing fires on a timer or on receipt of a response. Applying calls `PolicyWorkspacePage.tsx`'s own `applyAiProposal`, which only calls `setForm(...)` -- the same state update typing into any other field would trigger. Saving the rule afterward is the same explicit, separate "Save draft" click it always was.
- The model can only reference organisational entities that already exist. `policy_drafting_service._validate_entities` checks the proposed action against the real `FINANCIAL_VOCABULARY`, the proposed principal against `agent_service.list_principals` for *this* organisation, and an optional agent restriction against `agent_service.list_agents` for *this* organisation. A principal that genuinely exists in a different organisation is rejected identically to one that doesn't exist anywhere (`test_cross_tenant_principal_is_treated_as_unknown`). Nothing is ever silently created.
- Ambiguity produces a question, not a guess. The tool schema (`domain/policy_drafting/schema.py`) makes `proposal` nullable specifically so the model can return `clarifying_question` instead of fabricating a field it wasn't actually told.
- RBAC is unchanged, not bypassed. Both endpoints require the existing `Permission.RUNTIME_POLICY_EDIT` via the existing `require_permission` dependency -- the same permission the Manual builder itself already requires to make any change. There is no new permission, and no path that grants drafting access without also granting the ability to edit the rule by hand.

## Where it fits in the existing system

```
                         Policy Studio Manual builder (PolicyWorkspacePage.tsx)
                                            |
                    "Draft with AI" (secondary entry point, never overpowering Save)
                                            |
                                  DraftWithAIPanel.tsx
                             (Draft / Edit / Explain modes)
                                            |
                    POST /v1/policy-drafting/draft or /explain
                                            |
                              policy_drafting_service.py
                        (builds prompt, validates the response
                         against this organisation's real entities)
                                            |
                               AzureAIFoundryProvider
                        (the same AIProvider already used by
                          AI Policy Builder / AI Authority Builder)
                                            |
                              a DraftProposal, or a
                        clarifying_question / unknown_entities list
                                            |
                    DiffPreview + explicit "Apply proposal" click
                                            |
                    setForm(...) -- the SAME in-memory form state
                    the Manual builder's own fields already update
                                            |
                    Save draft -> Submit for review -> Approve ->
                    Compile -> Deploy (unchanged, human-driven, per policy)
```

The assistant's only output is a proposal for the form the human is already looking at. From the moment a proposal is applied, the resulting form state is indistinguishable from one a human filled in by hand, except `metadata.created_by` records `"draft_with_ai"` for provenance -- purely descriptive, the same convention the AI Policy Builder's `"ai-extracted"` tag already established.

## AI infrastructure reuse (no new platform introduced)

Per this milestone's own mandate to audit existing AI infrastructure before adding anything new: `policy_drafting_service.py` calls the exact same `AIProvider` Protocol (`domain/ai_provider/interface.py`) and the exact same production `AzureAIFoundryProvider` implementation the AI Policy Builder and AI Authority Builder already use in production, via `generate_structured(system_prompt, user_content, json_schema, schema_name, max_tokens)` -- forced structured/tool-call output, not free-text parsing. No new provider, no new model, no new credential path was added. If Azure AI Foundry isn't configured in an environment, `_provider()` raises `AIDraftingNotConfiguredError` rather than falling back to a fake chatbot for real users; both endpoints turn that into a `503` the frontend shows as a plain, honest "not available" message. The Manual builder remains fully usable without it.

`draft_or_edit` also reuses `CandidateRuntimePolicy` and `candidate_to_content()` from the AI Policy Builder (`domain/ai_policy_builder/provider.py`, `services/ai_policy_builder_service.py`) for the proposal's shape and its conversion into a `RuntimePolicyRequest`-shaped dict, rather than a second, parallel representation. The one field that dataclass has no concept of -- an optional Agent restriction -- is carried separately on the wrapping `DraftProposal`/`PolicyDraftResult` classes, so the shared, unrelated document-extraction pipeline is untouched.

## The merge, applying a proposal onto an existing rule

`policy_drafting_service.candidate_to_content()` always sets `description` and `constraints.expires` to `null`, and has no concept of `constraints.authority_id`, `constraints.mandate_id`, `constraints.enterprise_system_id`, or `metadata.owner`/`tags` at all -- because no natural-language instruction legitimately determines any of those. `PolicyWorkspacePage.tsx`'s `applyAiProposal` merges accordingly: scope, conditions, effect, and `delegated_by`/`evidence_required`/`risk_level` come from the proposal (the fields the assistant actually reasons about); everything else is kept from the rule as it existed before applying. An existing rule's own name is kept too, unless the form's name field was still empty. See `PolicyWorkspacePage.test.tsx`'s own coverage of this merge for the exact preserved/overwritten field list.

## Explain mode

Anchored in `describePolicy(form)` -- the exact plain-English sentence the builder already renders live -- passed from the frontend as `deterministic_summary`, not re-derived a second time in Python. The model elaborates on a question about already-true structured facts; it never reconstructs what the rule means independently, which would risk a second, potentially-drifting description of the same rule.

## Testing

`server/tests/unit/test_policy_drafting_service.py`: valid instruction, valid agent restriction, ambiguous instruction produces a clarifying question, unknown principal/action/agent rejected, cross-tenant principal treated as unknown, multi-policy honesty flag, not-configured error, explain anchored in the deterministic summary. `src/app/policy-studio/components/DraftWithAIPanel.test.tsx`: a valid proposal requires an explicit Apply click before reaching the caller, an unknown-entity response cannot be applied, a clarifying-question response cannot be applied, a failed request leaves the rule unchanged and offers retry. `src/app/policy-studio/PolicyWorkspacePage.test.tsx`: applying a proposal updates the fields it addresses and preserves the ones it doesn't, including on an existing rule that already has an Authority/Mandate chain and an Enterprise System set.
