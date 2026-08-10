# Azure Production Migration Program — Milestone 3: Conformance Report

**Status:** final. This is the Milestone 3 stop-condition gate.

## Absolute rules carried across every milestone

| Rule | Held? | Evidence |
|---|---|---|
| Never rebuild working systems unnecessarily | Yes | The `eastus2` resources were deleted only after the user's three-point evidence-gated approval (no production traffic, no production data, created solely by the failed apply); `centralus`'s already-succeeded resources (networking, storage, ACR, Postgres) were never touched again once created — only the missing Key Vault and its dependents were added in follow-up applies |
| Never introduce unnecessary technology | Yes | The identity-first Key Vault/Storage redesign was chosen specifically to **avoid** introducing a jump host/bastion/VM/self-hosted runner — the alternative that would have added new infrastructure was the one rejected |
| Never skip verification | Yes | Every fix was re-planned and re-validated before applying; the final state was confirmed with a real `terraform plan` showing zero drift, not assumed from a successful `apply` exit code |
| Never continue automatically past a gate | Yes | Stopped and reported, in full, at both real blocking failures this milestone hit (the eastus2 root causes, and the Key Vault naming collision) — proceeded only after explicit user approval each time |
| Always document decisions | Yes | This document plus the other 8 required deliverables, plus inline Terraform comments at every non-obvious fix (see `git diff` on `modules/*/main.tf`) |

## Milestone 3's own instructions

| Instruction | Held? | Evidence |
|---|---|---|
| Verify Azure CLI authentication first; stop if unavailable | Yes | `az account show` + `az group list` re-confirmed live at the start of this session before any command that touches Azure |
| Deploy Milestone 2's Terraform; no manual resource creation unless Azure requires an unavoidable bootstrap step | Yes | Every resource in `rg-payreality-staging-cus` was created by `terraform apply`. No manual `az resource create` of any kind occurred. The one true exception, `AZURE_MIGRATION/bootstrap/` (the Terraform-state storage account), predates this milestone and was already documented as the honest chicken-and-egg exception in Milestone 2 |
| Provision and verify every named service | Yes | See `MILESTONE_3_ENVIRONMENT_VERIFICATION.md` — each service individually verified with a live command, not inferred |
| Build and push the application container; document image/tag/digest/auth | Yes | See `MILESTONE_3_DEPLOYMENT_REPORT.md` |
| Configure Container Apps so the application starts successfully | Yes | Real image running, health/readiness passing, confirmed via live `curl` and container logs |
| Verify OPA works inside Azure Container Apps without redesigning it | Yes | `server/Dockerfile` and `entrypoint.sh` untouched; OPA confirmed running loopback-only exactly as designed |
| Populate placeholder secrets only where appropriate; verify managed-identity retrieval; no plaintext secrets in config | Yes | `DATABASE_URL` and the Postgres admin password are Terraform-generated and written directly to Key Vault, never through a variable; application-facing secrets (`EVIDENCE_SIGNING_KEY_B64` etc.) deliberately remain Milestone 5's placeholder, per Milestone 2's own established design |
| Postgres: empty database, required roles, connection validated — no data migration | Yes | Schema migrated to head via the app's own startup migration run; zero data rows moved from Render |
| Storage: required containers, managed-identity access verified | Yes | 3 containers present; `Storage Blob Data Contributor` confirmed on the app identity; anonymous access confirmed rejected (`409`) |
| Verify observability without configuring alert rules yet | Yes | Log Analytics ingestion proven with a live KQL query; zero alert rules created. App Insights gap disclosed, not hidden — see `MILESTONE_3_KNOWN_ISSUES.md` |
| Verify networking end-to-end | Yes | See `MILESTONE_3_ENVIRONMENT_VERIFICATION.md`'s Networking section |
| Security review: no public database, no public Key Vault (unauthenticated), no leaked secrets, TLS, least privilege | Yes | See `MILESTONE_3_SECURITY_REVIEW.md` — every claim backed by a live test, not a config read |
| Cost review against Milestone 2's estimates | Yes | See `MILESTONE_3_COST_REPORT.md` — live retail pricing for the two SKUs actually re-priced, both within or exactly matching estimate |
| Validate Terraform state/plan cleanliness, startup, reachability, telemetry, no drift | Yes | Final `terraform plan`: *"No changes. Your infrastructure matches the configuration."* |
| 9 required documents | Yes | This document plus the other 8, all under `AZURE_MIGRATION/` |
| Respect repository rules; explain any exception touching Runtime Governance/Specification/Product Roadmap/application logic | Yes, no exception needed | Zero files under `server/`, `SPECIFICATION/`, or `PRODUCT_ROADMAP/` touched at any point |
| Stop once Azure hosts a functioning environment; Render remains production; no DNS change, no customer traffic, no database migration, no production cutover | Yes | All held. This report is the stop point |

## Deviations from the milestone's literal instructions, and why

1. **Region changed from the implicit `eastus2` default to `centralus`** — not a deviation from intent, a response to a genuine subscription-level capacity restriction Azure itself imposed, discovered via `az postgres flexible-server list-skus`, not chosen for convenience.
2. **Key Vault's network posture changed from fully-isolated to public-endpoint-with-RBAC** — an explicit, user-approved trade-off (see `MILESTONE_3_SECURITY_REVIEW.md`), not a unilateral shortcut. The alternative (a jump host) was presented and rejected in favor of this one.
3. **Four Terraform provider-quirk fixes** (`ignore_changes` on three attributes, a diagnostic-settings target/metric-category fix) — none change the deployed resource's actual configuration; each stops the provider from proposing a spurious or outright-rejected change on every future `plan`/`apply`.

None of these required touching application code, `SPECIFICATION/`, or `PRODUCT_ROADMAP/`.

## Gate status

**Passed.** Stopping per the Completion Gate — not beginning Milestone 4, not touching Render or DNS, not continuing automatically.
