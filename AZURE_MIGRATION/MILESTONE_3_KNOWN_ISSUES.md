# Milestone 3: Known Issues

Ranked by what blocks production migration versus what is expected and deferred by design.

## 1. Evidence signing key is still a placeholder — expected, not a bug

`EVIDENCE_SIGNING_KEY_B64` in Key Vault holds `PENDING-MILESTONE-5-MANUAL-ENTRY`, not real key material. At startup, the application logs `signing_key_registration_failed_at_startup` (`nacl.exceptions.ValueError: The seed must be exactly 32 bytes long`) and **continues running** — it does not crash. This is the intended behavior of the placeholder design established in Milestone 2 (`modules/key-vault/main.tf`'s own comment: "Secrets should never live inside Terraform variables"). Evidence-signing-dependent features will not function correctly in this environment until Milestone 5 sets the real value via `az keyvault secret set`, out-of-band. **Blocks:** signature-dependent functional testing, not the platform itself.

## 2. Application Insights receives no application-level telemetry yet

The `appi-payreality-staging-cus` resource is provisioned and reachable, but its `requests` table is empty. Azure Container Apps does not auto-instrument to Application Insights the way App Service does — that requires either an OpenTelemetry/App Insights SDK wired into the application with a connection string, or Container Apps' own Dapr/OpenTelemetry integration, neither of which exists in the current codebase. Adding either is an application-code change, out of scope for this milestone's "do not modify application logic unless deployment absolutely requires it" rule — it doesn't; the platform starts and runs correctly without it. Platform-level observability (container logs, resource diagnostic logs) **is** confirmed working via Log Analytics. **Recommendation:** scope real APM instrumentation as an explicit, small future milestone item rather than silently declaring App Insights "done."

## 3. Key Vault naming collision residue

`kv-pr-staging-adzg` remains soft-deleted and unpurgeable until `2026-11-08`, permanently bound to the now-abandoned `eastus2`. Not a functional issue (the active vault is `kv-pr-staging-lu2swm`), but worth remembering: **the same naming convention now used for Key Vault must be applied to `prod.tfvars` before Milestone 4** touches production, or the same class of collision could recur there.

## 4. `az acr build`'s local log streaming is unreliable on this Windows/Git-Bash setup

Not an Azure issue — the local `az` CLI's log-streaming client crashed once on a Windows console encoding error (`UnicodeEncodeError` in `colorama`) while a remote ACR Task build was genuinely still running and succeeded. Anyone re-running builds from this same local environment should check `az acr task list-runs` for the real status rather than trusting a crashed streaming client as a build failure.

## 5. Carried forward from Milestone 1 / 2, still open

- Render's database expiry risk (Sprint 1's Task T1) — still unresolved, still the one risk the "Render stays production until Azure is fully verified" principle depends on.
- Azure CLI MFA/device-code friction — resolved for this session's authentication, but any future re-authentication in a non-interactive shell will hit the same flow.

## Not an issue: two benign Terraform-managed in-place corrections

During re-planning, Terraform proposed removing a `Microsoft.Storage` service endpoint Azure had auto-added to the Postgres subnet, and clearing an auto-assigned availability `zone` value this config never asked for. Both are cosmetic, non-destructive reconciliations, not defects — see `MILESTONE_3_DEPLOYMENT_REPORT.md`'s provider-quirks table for the `zone` fix specifically (which required `ignore_changes` after the provider rejected the change outright once).
