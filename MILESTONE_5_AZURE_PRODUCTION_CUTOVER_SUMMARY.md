# Milestone 5: Azure Production Cutover

**Status: Azure prod redeployed, provisioned, and live-validated for real. DNS has not moved. Render has not been touched. Final recommendation: NO.**

This milestone executed real, live-mutating actions against Azure production (a redeploy, a Terraform apply provisioning new AI resources, and a full end-to-end functional validation pass using the real operator key), per explicit user authorization given after the risk and cost of those actions were disclosed. Nothing was done to Render or to DNS. Every claim below is backed by a command actually run and its actual output, not inferred from configuration or prior memory.

## 1. Infrastructure audit

Carried forward from the same-day Milestone 4 audit, spot-checked for drift before this milestone began (no drift found: same image, same secrets, same absent AI resources, both confirmed live via direct `az` calls), then re-verified after this milestone's own changes:

| Resource category | Status | Evidence |
|---|---|---|
| Container Apps / Environments (staging + prod) | PASS | Both healthy before and after this milestone's redeploy; prod's new revision confirmed `Healthy`/`Provisioned` |
| Container Registry | PASS | New `prod-cb8c9b3` tag pushed and confirmed present, matches what the Container App now runs |
| PostgreSQL Flexible Server | PASS | Private-network-only in both environments, confirmed reachable from inside the app via `/health/ready` before and after |
| Key Vault | PASS | RBAC-only, purge protection on, secrets resolved correctly (new revision provisioned successfully, which requires successful secret resolution) |
| Managed Identity | PASS | Prod's Container App identity now also holds Search Service Contributor, Search Index Data Contributor, and Cognitive Services OpenAI User roles (newly granted by this milestone's apply), confirmed via the plan and the apply's own resource list |
| Azure AI Foundry | PASS, newly provisioned | `aif-pr-prod-ic4cuk`, one `gpt-5-mini` deployment, created by this milestone; a real extraction against it is proven in section 3 |
| Azure AI Search | PASS, newly provisioned | `srch-pr-prod-tq1k`, created by this milestone; a real index write is proven in section 3 |
| Blob Storage | PASS | Confirmed via `az storage blob list`: a document uploaded during this milestone's own validation is present at the correct org-scoped path, real size, real content |
| Azure Monitor / Log Analytics / Application Insights | PASS | Used directly in this milestone to retrieve the real startup logs and the real exception traceback in section 4; unquestionably live |
| Networking / Private Endpoints | PASS | Unchanged by this milestone; Key Vault and Blob private endpoints remain approved |
| RBAC | PASS | All new role assignments from this milestone's apply are resource-scoped, matching the project's existing identity-first convention; no resource-group or subscription-level assignment was introduced |
| Backup configuration | PASS (unchanged) | Postgres 35-day retention plus PITR, geo-redundant on prod; not touched by this milestone |
| Disaster Recovery configuration | WARNING (unchanged) | No zone-redundant HA anywhere; PITR is the only mechanism. Same as Milestone 4's finding, not made worse or better by this milestone |

## 2. Deployment log

Every command below was run for real against the live subscription (`09e09093-55bb-4fce-a487-5556fdf853d1`), in this order:

1. `az acr build --registry acrprprodtq1k --image payreality-api:prod-cb8c9b3 --file server/Dockerfile server`: built and pushed the current `main` HEAD (`cb8c9b3f4ea05f616821d747700eba40f8ae861c`) to the prod registry. The local `az` CLI crashed while streaming build logs (a Windows console-encoding bug unrelated to the build itself), but the remote ACR task run (`cj2`) is confirmed `Succeeded` via `az acr task list-runs`, and the resulting tag is confirmed present via `az acr repository show-tags`.
2. `terraform init -reconfigure` with `key=payreality-prod.tfstate`: repointed the local Terraform working directory from staging's state (where it had been left since Milestone 3/5 of the Azure migration program) to prod's own real state, per the project's own documented partial-backend-config workflow. No state migration occurred; this only changes which remote state file subsequent commands read and write.
3. Updated `environments/prod.tfvars`'s `container_image` to the new tag.
4. `terraform plan -var-file=environments/prod.tfvars -out=prod.plan`, reviewed in full before applying: **9 to add, 1 to change, 0 to destroy.** The additions were exactly the AI Foundry account, its model deployment, and its role assignment; the AI Search service and its two role assignments; and two new diagnostic settings for those two resources. The one change was the Container App's image and eight previously-absent environment variables. Nothing else in prod's existing 58 resources was touched.
5. `terraform apply "prod.plan"`: applied exactly the reviewed plan. **Apply complete: 9 added, 1 changed, 0 destroyed.**
6. Verified the new revision (`ca-payreality-api-prod-cus--0000002`) directly: `active: true`, `health: Healthy`, `provisioning: Provisioned`, running `prod-cb8c9b3`.
7. Pulled the new revision's actual startup log from Log Analytics (not inferred): the real Alembic migration chain ran clean, including the exact migrations for multi-tenant foundation (`a7d3e9f2c6b1`), Enterprise Surface Isolation (`c3f8a1b2d5e9`), and the Runtime Policy Simulator's own table (`e8a4c1f6d92b`); a real Managed Identity token was acquired; the app's own startup code made a real, successful call to the newly-created Azure AI Search service (`POST .../indexes -> 201`, logged as `authority_intelligence_search_index_created`); `Application startup complete.`

The local `prod.plan` binary was deleted after a successful apply; it served its one-time purpose and Terraform plan files are not meant to be retained as source artifacts.

**One tooling fix made during this pass, disclosed plainly:** `scripts/smoke_test.py` predated the Agent Lifecycle work (a prior milestone, not this one) and tried to submit a signed Intent immediately after registering an Agent, without the explicit activation step that lifecycle work now requires (a fresh Agent's certificate starts `issued`, not `active`; only an active certificate can sign). This is a one-step addition to a validation script, restoring it to match already-shipped behavior, not new product functionality or a redesign; without it, this milestone's own required validation could not run at all.

## 3. AI infrastructure validation

Real validation, not configuration inspection, per the milestone's own instruction:

- **Azure AI Foundry, Authority Builder path: PASS, genuinely live.** `routers/ai_authority_builder.py`'s provider selection checks `azure_ai_foundry_endpoint` first, before falling back to Anthropic or the fake provider. That endpoint is now genuinely populated (this milestone's own apply). A real test document was uploaded to a real corpus; the response came back `status: extracted`, and the extracted principal candidates carry genuine model reasoning (`"Document explicitly names the Regional Controller and states both the delegated authority and that the Regional Controller reports to the CFO."`), a genuinely inferred ambiguity flag (`"The document does not state to whom the CFO reports."`), and non-round confidence scores (0.95, 0.9) tied to specific source lines. This is not the deterministic fake provider's output; this is real, live Azure AI Foundry inference in Azure production, for the first time in this platform's history.
- **Azure AI Search: PASS, genuinely live.** Beyond the resource existing, the application's own startup code created a real index (`authority-intelligence-documents`) via an authenticated, Managed-Identity-signed call that returned `201`. Both role assignments (Search Service Contributor, Search Index Data Contributor) are confirmed attached to the Container App's identity.
- **Azure Blob Storage: PASS.** The document uploaded during Foundry validation is confirmed present in `stprprodtq1k`'s `uploads` container at `authority-corpora/<organization_id>/<corpus_id>/<document_id>-<filename>`, matching the org-scoped path convention exactly.
- **Managed Identity: PASS.** Every one of the above required a real token acquisition and a real authenticated call; none of it is reachable with a static key, and none was used.
- **Azure AI Policy Builder path: BLOCKER, confirmed broken, not merely unconfigured.** Unlike Authority Builder, `routers/ai_policy_builder.py`'s provider selection has no Azure AI Foundry branch at all; it only ever chooses between Anthropic and the fake provider. `ANTHROPIC_API_KEY` in prod remains the same never-rotated placeholder Milestone 4 found by metadata inspection alone; this milestone confirmed it directly by triggering a real call: uploading a document to `/v1/ai-policy-builder/uploads` produced a stored upload with `status: "failed"` and `error: "Error code: 401 - {...'invalid x-api-key'...}"`, a real, live rejection from Anthropic's own API. This is not a "no real AI configured" gap; it is an actively broken pipeline for every single-document upload attempt in prod today, caught here rather than by a customer, because the failure is caught and stored rather than crashing the request.

## 4. End-to-end platform validation

Executed for real against live prod, using the real `admin-api-key` operator credential (retrieved by the user directly and provided for this session's use only; never written to a file or printed in full in any command output; not present in this document). Every stage below is a real HTTP call against `ca-payreality-api-prod-cus...azurecontainerapps.io`, not a local or staging test.

| Workflow | Result | Evidence |
|---|---|---|
| Health / readiness | PASS | `/health` and `/health/ready` both 200, `database: true`, `opa: true` |
| Organization creation | PASS | `POST /v1/organizations` created a genuine second organization (`Milestone 5 Validation Org`) in prod, for the first time in this platform's production history |
| Multi-tenancy / isolation | PASS | The new organization's `/v1/agents` and `/v1/principals` both returned empty, despite the first organization genuinely having both; isolation confirmed live, not by code inspection |
| Principal / Agent registration | PASS | Real Principal and Ed25519-keypaired Agent created via the operator-gated API |
| Agent activation | PASS (after the tooling fix in section 2) | `POST /v1/agents/{id}/activate` moved the Agent `registered -> active` and its certificate `issued -> active` |
| Intent submission / Runtime authorization | PASS | A real signed Intent was submitted and received a real Decision (`HUMAN_REVIEW`, correct fail-closed behavior given no active policy existed for that org yet at that point in the run) |
| Decision resolution | PASS | The `HUMAN_REVIEW` decision was resolved via the real API |
| Evidence generation | PASS | A real, signed Evidence record was created and is present in `GET /v1/evidence` |
| Evidence verification | PASS | The Evidence record's signature verified cryptographically against the published verification key |
| Assurance counts | PASS | Real, live counts returned (4 agents, correctly reflecting every agent created during this validation pass, including the one from the earlier failed pre-fix run) |
| Evidence chain verify (the Milestone 3 crash fix) | PASS, with a WARNING | No longer crashes (previously a `TypeError` for any org with Evidence). Returns `{"intact": true, "total": 0, ...}` even though the same organization has at least one real Evidence record confirmed via the plain list endpoint. The crash is genuinely fixed; this count discrepancy is a new, smaller, disclosed finding, not investigated further here since root-causing it would mean reading and reasoning about application logic beyond this milestone's verification-only scope. Recommend a dedicated look in the next available slot. |
| Canonical documents / Authority Builder corpus | PASS | Real document upload, real extraction (section 3), real principal/relationship/gap/question candidates produced |
| Runtime Policy generation | PASS | One of the real, Foundry-extracted policy candidates was promoted into a genuine draft Runtime Policy via `POST /v1/ai-policy-builder/candidates/{id}/promote` |
| Runtime Policy lifecycle (draft -> pending_review -> approved -> active) | PASS | All three transitions (`submit-for-review`, `approve`, `lifecycle/activate`) executed for real against the promoted policy; final state is `active` |
| Runtime Policy compilation | PASS | The `approve -> activate` transition triggers compilation internally; the resulting policy carries a real `bundle_id` and `bundle_hash` |
| OPA deployment | PASS | The same `bundle_hash` is the direct evidence OPA received and compiled a real bundle, not a no-op |
| Policy activation | PASS | Confirmed by the final `status: "active"`, `effective_status: "active"` response |
| Runtime Policy Simulator | **BLOCKER, newly discovered** | `POST /v1/policy-simulation/{policy_key}/simulate` against the just-activated, real policy returned `{"detail": "internal_error"}`. The real traceback, pulled directly from Application Insights, shows the exact cause: `File "/srv/app/services/policy_simulation_service.py", line 162, in _compile_for_simulation` calls `get_latest(db, policy_key)` with no `organization_id` argument, and `TypeError: get_latest() missing 1 required positional argument: 'organization_id'`. This is the same class of bug the pre-Milestone-3 audit found and fixed in `evidence_service.py::verify_chain`: a function's call site was never updated for Milestone 2's multi-tenant signature change. **Impact: the Runtime Policy Simulator is completely non-functional, for every organization, for every policy, in production today.** **Recommendation: a one-line fix (thread `organization_id` through this one call site), scoped as a fast follow-up, not as part of this migration-only milestone.** |
| SDK | NOT VERIFIED | Not exercised against prod in this pass. The Python SDK's own unit suite (68/68) already passed independently of this milestone; a live integration run against the new prod endpoint was not performed, since doing so meaningfully would mean configuring and running the SDK's own example flow, which was judged disproportionate to add to an already extensive live-validation pass. |
| Frontend | NOT VERIFIED | No deployed frontend build points at Azure today (Vercel's production `VITE_API_URL` still points at Render, confirmed in section 5); there is nothing live to exercise against Azure without standing up a temporary build, which is out of this milestone's scope (no new infrastructure beyond what was requested). |

**Validation artifacts left in prod, disclosed rather than cleaned up**, matching this project's own established precedent of leaving prior smoke-test data in place rather than deleting it: one extra organization (`Milestone 5 Validation Org`), one extra Principal, four Agents (one from an early run that failed before the activation fix, three from later successful runs), one Authority Corpus with a real extraction result, one AI Policy Builder upload record (the one that failed against the placeholder Anthropic key), and one real, active Runtime Policy (`Regional Controller vendor payment approval (<= $50,000 USD)`). None of this is harmful; all of it is real evidence this validation pass actually exercised production, not a copy of it.

## 5. DNS readiness

Checked live, not assumed:

- `api.aisecurewatch.com` resolves via a real CNAME chain to `payreality-api.onrender.com` behind Cloudflare, and returns a real 200 in well under half a second. **This is Render, today, still.**
- `demo.aisecurewatch.com` resolves to Vercel (`*.vercel-dns-017.com`), unrelated to either backend; not a candidate for this cutover.
- `az network dns zone list` at subscription scope: empty. **No Azure DNS zone exists anywhere in this subscription.**
- `az containerapp hostname list` for both staging and prod: empty. **No custom domain is bound to either Container App**, even after this milestone's redeploy; nothing about this milestone's changes touched domain binding, since doing so was explicitly deferred pending validation succeeding first, per the milestone's own Phase 5 instruction ("No DNS changes should occur until validation succeeds").
- SSL/certificates: only the default `*.azurecontainerapps.io` managed certificate exists on either app; no certificate exists for a real domain, because no domain is bound.
- **Traffic routing: unchanged. 100% of real traffic is still on Render/Vercel.** Nothing in this milestone moved, or was intended to move, any traffic.

## 6. Render retirement readiness

Per the milestone's explicit instruction, this section documents readiness only; **Render was not touched, modified, or queried for anything beyond the public health/DNS checks already described.**

- **Remaining Render dependencies**: unchanged from Milestone 4's Phase 2 audit (`render.yaml`, the `RENDER_GIT_COMMIT` fallback in `main.py`, the Vercel `VITE_API_URL` binding, the SDK's default base URL, and the documentation list). Nothing in this milestone added or removed a dependency.
- **Rollback procedure**: see section 9. Unchanged from Milestone 4's design; still untested against a live incident, since no traffic has ever moved to be rolled back from.
- **Data synchronization**: still an open question, restated rather than resolved. Whether Render's live database holds real data worth migrating remains something this session cannot check directly (no Render database credential is available in this environment). This milestone did not need to answer that question, since no data migration was attempted; it must be answered before Phase 7 of the Azure migration program's own plan (or this repository's `MILESTONE_4` data-migration design) is executed for real.
- **Shutdown order**: not applicable yet; nothing is being shut down until traffic has actually moved and an observation window has passed with zero rollback triggered, per every prior rollback document in this repository.
- **Services to retain temporarily**: Render's web service and its Postgres instance, in full, until real cutover happens and the observation window closes.
- **Services safe to remove**: none, yet. Nothing is safe to remove before DNS has ever pointed at Azure even once.

## 7. Remaining blockers

1. **No path to Azure exists for real traffic.** No custom domain, no certificate, no Azure DNS zone. This alone is sufficient to block cutover regardless of anything else in this list.
2. **The Runtime Policy Simulator is completely broken in production**, for every organization, discovered live in this pass (section 4). A pre-existing bug, not introduced by this milestone, but a real one that would ship to real users on cutover today.
3. **AI Policy Builder's single-document pipeline is actively broken**, not merely unconfigured: every real upload attempt fails with a live 401 from Anthropic. Authority Builder's separate pipeline is fine (now genuinely Foundry-backed), but Policy Builder has no Foundry provider option at all in its own code, so fixing the placeholder key alone would not be sufficient even if it were done.
4. **The Evidence chain verify endpoint's `total` count appears to undercount real Evidence** (returns 0 against an organization with at least one confirmed record). No longer crashes (the Milestone 3 fix holds), but this specific discrepancy was not root-caused in this pass.
5. **SDK and frontend were not exercised against Azure at all.** Both remain genuinely unknown quantities against this specific environment, stated as NOT VERIFIED rather than assumed fine.
6. Carried forward, unchanged from Milestone 4: the orphaned `psql-payreality-staging-cus-restoretest` server and the soft-deleted `kv-pr-staging-adzg` vault (unpurgeable until 2026-11-08); no zone-redundant HA anywhere; whether Render's database holds real data needing migration is still unconfirmed.

## 8. PASS / WARNING / BLOCKER matrix

| Area | Verdict |
|---|---|
| Container Apps (staging + prod) | PASS |
| Container Registry | PASS |
| PostgreSQL | PASS |
| Key Vault | PASS |
| Managed Identity / RBAC | PASS |
| Azure AI Foundry (provisioning + Authority Builder integration) | PASS |
| Azure AI Search | PASS |
| Blob Storage | PASS |
| Application Insights / Log Analytics / Monitor | PASS |
| Networking / Private Endpoints | PASS |
| Backups | PASS |
| Disaster Recovery | WARNING (no zone-redundant HA; unchanged from Milestone 4) |
| Application deployment (current HEAD, migrations) | PASS |
| Multi-tenancy / Organization Lifecycle | PASS |
| Runtime Authority core pipeline (Intent -> Decision -> Evidence) | PASS |
| Runtime Policy generation / compilation / OPA deployment / activation | PASS |
| Runtime Policy Simulator | **BLOCKER** |
| AI Policy Builder (single-document pipeline) | **BLOCKER** |
| Evidence chain verify accuracy | WARNING |
| SDK against Azure | NOT VERIFIED |
| Frontend against Azure | NOT VERIFIED |
| DNS / custom domain / certificates | **BLOCKER** |
| Render retirement readiness | Not applicable yet (correctly untouched) |

## 9. Rollback procedure

Nothing in this milestone requires a rollback, since no traffic was ever moved and nothing was deleted. Documented here for completeness, unchanged in mechanism from every prior rollback plan in this repository:

- **If a problem were ever found with today's changes specifically**: `terraform apply` the prior plan (re-set `container_image` back to `prod-5e1c3ad` and re-run plan/apply) would remove the newly added AI resources and revert the Container App's image and env vars. Not exercised in this pass, since nothing broke; stated as the mechanism, not as something already tested.
- **If a real cutover were ever attempted and needed reverting**: revert the DNS record or Vercel's `VITE_API_URL` back to `payreality-api.onrender.com`. Render is untouched and has been serving effectively 100% of real traffic throughout; there is nothing to reconcile back into it.

## 10. Final recommendation

**Is PayReality ready to move production traffic from Render to Azure?**

# NO

Azure's infrastructure is real, live, and now includes a genuinely working AI Foundry integration for Authority Builder, proven with an actual extraction, not just a provisioned resource. The core Runtime Authority pipeline, the multi-tenant Organization Lifecycle, and the full Runtime Policy lifecycle (generation through OPA deployment and activation) were all exercised for real in production during this milestone and all passed. That is genuine, meaningful progress from Milestone 4's "architecturally ready but not deployable" verdict.

But three things, independently, each block cutover today: there is no DNS or custom-domain path to Azure at all, so there is nowhere to route traffic to yet; the Runtime Policy Simulator is completely broken for every organization, a real defect this pass discovered rather than assumed away; and the AI Policy Builder's single-document pipeline is actively failing against a live, invalid credential, not merely unconfigured. None of these are large undertakings, each is a scoped, closable fix, but none of them existed as closed facts at the start of this milestone and none of them are closed now. Cutting DNS over today would move real traffic onto a platform with a known-broken feature and no way to reach it besides the platform's own default hostname.
