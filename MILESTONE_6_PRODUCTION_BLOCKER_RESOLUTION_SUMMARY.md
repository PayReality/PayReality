# Milestone 6: Production Blocker Resolution

**Status: both blockers Milestone 5 found are fixed and live-verified in Azure production. DNS/domain readiness is unchanged and remains the one thing standing between this platform and a real cutover.**

This milestone targeted exactly the two functional blockers Milestone 5's live validation discovered: the Runtime Policy Simulator crashing on every call, and AI Policy Builder actively failing against an invalid credential. Both are fixed, redeployed to the same live Azure production environment, and re-verified with real API calls, not local tests alone. A companion architecture review (`AI_PIPELINE_CONSOLIDATION_REVIEW.md`) answers the deeper question of whether AI Policy Builder should exist as a separate pipeline at all.

## 1. Root cause analysis

### Runtime Policy Simulator

The crash Milestone 5 found (`get_latest() missing 1 required positional argument: 'organization_id'`) was one symptom of a broader gap: nothing in `policy_simulation_service.py` or `routers/policy_simulation.py` had ever been updated for Milestone 2's Multi-Tenant Foundation, even though the feature itself (Authority Intelligence Program, Phase 4) was built after that milestone shipped. Tracing the complete execution path found:

- `_compile_for_simulation` called both `get_latest(db, policy_key)` and `_other_active_policies(db, policy_key)` with no `organization_id`, even though both functions have required it since Milestone 2. Every caller of this function, `simulate` and `run_batch`, inherited the crash.
- The router itself never resolved an organization at all: no endpoint in `policy_simulation.py` had an `organization: Organization = Depends(get_current_organization)` parameter, unlike every other router in this codebase touching organization-scoped data.
- `SimulationScenario.organization_id`, a real column added additively in Milestone 2, was never populated by `create_scenario` and never filtered by `list_scenarios`/`get_scenario`. This is a second, independent isolation gap, not just a crash: a caller who knew another organization's scenario UUID could read, list, or re-run it. The reason this was never caught: `tests/integration/test_policy_simulation_opa.py`, this feature's only existing test coverage, deliberately tests the OPA-dependent domain layer directly and never calls through the service layer at all, per that file's own documented convention. Nothing anywhere exercised `policy_simulation_service.py`'s own DB-orchestration functions.

### AI Policy Builder

Not a configuration gap. `routers/ai_policy_builder.py::_provider()` had exactly two options, Claude or the fake provider, with no Azure AI Foundry branch at all. This was an omission, not a deliberate vendor choice: the same vendor-neutral seam Authority Builder already used (`domain/ai_provider`) was sitting there unused. See `AI_PIPELINE_CONSOLIDATION_REVIEW.md` for the full architecture analysis, including the finding that AI Policy Builder's entire output shape (`CandidateRuntimePolicy`) is already one of Authority Builder's own eight extraction categories, and that a third, separate, and genuinely dead provider hierarchy (`domain/extraction/`) had existed, unused, since this project's first commit.

## 2. Code changes

**Runtime Policy Simulator** (`server/app/services/policy_simulation_service.py`, `server/app/routers/policy_simulation.py`): every service function (`_compile_for_simulation`, `simulate`, `run_batch`, `create_scenario`, `list_scenarios`, `get_scenario`, `run_scenario`) now takes and threads `organization_id`. `create_scenario` verifies the target policy belongs to the caller's organization (via `get_latest`) before stamping the new row; `list_scenarios` does the same before querying; `get_scenario` checks the row's own `organization_id` directly. Every router endpoint now resolves `organization: Organization = Depends(get_current_organization)` and passes `organization.id` through. No change to Runtime Authority, OPA evaluation, or the compiler.

**AI Policy Builder** (`server/app/domain/ai_policy_builder/`): `extraction_shared.py` (new) holds the system prompt, JSON schema, and result parsing, extracted out of `claude_provider.py` (now trimmed to just the Anthropic API call) so a second provider never duplicates that logic, mirroring `domain/ai_authority_builder/extraction_shared.py`'s already-established split exactly. `azure_foundry_provider.py` (new) is a thin adapter over the shared `AzureAIFoundryProvider` client, structurally identical to Authority Builder's own Foundry adapter. `routers/ai_policy_builder.py::_provider()` now checks Foundry first, Claude second, the fake provider last; its `/status` endpoint reports `ai_enabled` against that same ordering instead of only ever checking the Anthropic key.

**Dead code removed**: `domain/extraction/` (three files), confirmed to have zero callers anywhere in the repository and already flagged as dead in `SPECIFICATION/17_LEGACY_COMPONENTS.md`, which is updated to record the deletion.

## 3. Tests added

- `server/tests/unit/test_policy_simulator_multi_tenant.py` (9 tests): reproduces the exact production `TypeError` as a passing "no longer raises" case, confirms organization filtering in the actual SQL statement text (matching this codebase's established assertion style), confirms cross-organization lookups fail closed as not-found rather than crashing or leaking data, and confirms every Test Scenario CRUD function's new organization stamping and isolation.
- `server/tests/unit/test_azure_foundry_policy_builder_provider.py` (5 tests): mirrors the existing Authority Builder Foundry provider test file exactly, confirming the new provider's contract, its provider-selection priority, and cross-provider output consistency with Claude and the fake provider.

Full suite after these changes: **359 unit tests, 14 integration tests, all passing** (up from 354/14 before this milestone; zero regressions, confirmed by running both suites locally before any deployment).

## 4. Live validation evidence

Every check below is a real HTTP call against `ca-payreality-api-prod-cus...azurecontainerapps.io`, run after redeploying (`terraform apply`, 0 added, 1 changed, 0 destroyed, image `prod-54c4411`) and confirming the new revision `--0000003` healthy and receiving 100% traffic.

| Check | Result |
|---|---|
| Simulator: the exact call that crashed in Milestone 5 | **Fixed.** Real `ALLOW` decision, correct condition evaluation ($25,000 <= $50,000), real bundle hash, full rule/authority trace |
| Simulator cross-organization isolation | **Fixed.** A second organization attempting to simulate or save a Test Scenario against the first organization's policy_key gets `404 runtime_policy_not_found`, not data and not a crash |
| AI Policy Builder: the exact upload that failed with a real 401 in Milestone 5 | **Fixed.** `status: "extracted"`, `error: null`. The resulting candidates carry genuine, non-templated model output (two distinct grants, "Regional Controller" and "CFO," with different thresholds, real confidence scores of 0.9 and 0.85, and genuinely inferred `missing_fields`), confirming real Azure AI Foundry inference, not the deterministic fake provider's single hardcoded candidate |
| AI Authority Builder / Azure AI Search | **Still working**, unaffected by this milestone's changes; `ai_enabled: true` confirmed genuinely backed by a real Foundry endpoint (established in Milestone 5, re-confirmed here) |
| Blob Storage | **Still intact**; the Milestone 5 validation document is still present at its org-scoped path |
| Evidence chain verify | **Still not crashing** (the Milestone 3 fix holds); the `total: 0` discrepancy against an organization with confirmed real Evidence, noted in Milestone 5, persists unchanged and was not investigated further, since it is unrelated to this milestone's two targeted blockers |
| Multi-tenancy | **Confirmed again**, via the two new Simulator isolation checks above, on top of the Organization Lifecycle checks already proven in Milestone 5 |
| Health / readiness | `200` / `{"ready": true, "checks": {"database": true, "opa": true}}`, both before and after the redeploy |
| Container logs | No errors or tracebacks in the new revision's logs |

## 5. DNS readiness, reassessed

Unchanged, because nothing in this milestone touched it: `az network dns zone list` returns empty, `az containerapp hostname list` returns empty for prod, and `api.aisecurewatch.com` still resolves to Render. Fixing the Simulator and AI Policy Builder removed two functional reasons not to cut over; it did not create a path to cut over to. That is a separate, purely infrastructural step (bind a custom domain and certificate to the prod Container App, then point DNS or Vercel's `VITE_API_URL` at it), already designed in `MILESTONE_4_AZURE_PRODUCTION_READINESS_SUMMARY.md`'s Phase 7 and not this milestone's stated scope.

## 6. Remaining risks

1. **No DNS or custom-domain path to Azure exists**, independent of application correctness. This is the one remaining blocker to an actual cutover, and it is not a code defect.
2. **Evidence chain verify's `total: 0` discrepancy** (Milestone 5's finding) remains open and un-root-caused.
3. **The deeper AI-pipeline consolidation** (`AI_PIPELINE_CONSOLIDATION_REVIEW.md`'s recommendation to eventually retire AI Policy Builder as an independent pipeline in favor of Authority Builder's richer corpus model) is documented, not executed, and remains real product-scoped work for a future milestone.
4. Carried forward, unchanged from Milestone 4/5: the orphaned staging restore-test Postgres server and soft-deleted Key Vault; no zone-redundant HA anywhere; whether Render's live database holds real data needing migration is still unconfirmed.
5. **SDK and frontend were not re-exercised against Azure in this pass**, matching Milestone 5's same disclosed gap; this milestone's validation was scoped to the two blockers it targeted plus a regression sweep of the areas Milestone 5 already proved.

## 7. Updated production recommendation

**Is PayReality ready for DNS cutover?**

**Not yet, and the reason has changed since Milestone 5.** Both functional blockers that milestone found, the Simulator crashing for every organization and AI Policy Builder actively failing against an invalid credential, are now fixed and live-verified in the same production environment DNS would eventually point at. What remains is not an application defect: **no custom domain or certificate is bound to the production Container App, and no DNS record anywhere points at Azure.** That is a scoped, well-understood, already-designed infrastructure step (Milestone 4's Phase 7), not a code fix, and it is the only thing left before a real cutover attempt becomes possible rather than premature. Once a domain and certificate are bound, the platform's own application correctness is no longer the blocking question; the DNS cutover plan itself, with its TTL-lowering and rollback steps, already exists and is ready to execute.
