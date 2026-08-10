# Azure Runbook

**Status:** living document, first published Milestone 4. Supersedes `MILESTONE_3_OPERATIONAL_CHECKLIST.md` as the day-to-day reference (that file remains as the historical record of what Milestone 3 knew at the time); update this file, not that one, as operational knowledge grows.

Current environment: staging only, `rg-payreality-staging-cus`, `centralus`. No production environment exists yet — see `MILESTONE_4_PRODUCTION_CUTOVER_READINESS_ASSESSMENT.md` for what's still required before one does.

## Re-running Terraform

```
cd AZURE_MIGRATION/terraform
terraform init \
  -backend-config="resource_group_name=rg-payreality-tfstate" \
  -backend-config="storage_account_name=sttfstatepr8p3t4s" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=payreality-staging.tfstate"
terraform plan -var-file="environments/staging.tfvars"
```

Always review the plan before applying. `terraform.exe` on the primary workstation used for this program is at
`C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe\terraform.exe` — not on `PATH` in Git Bash.

## Building and deploying a new application image

```
az acr build --registry acrprstagingadzg --image payreality-api:staging-<short-sha> server/
```

Update `container_image` in `environments/staging.tfvars` to the new tag, then re-apply. If `az acr build`'s log streaming crashes locally (a Windows console-encoding bug, not a build failure), confirm real status with `az acr task list-runs --registry acrprstagingadzg --top 3 -o table`.

## Checking the running application

```
az containerapp logs show --name ca-payreality-api-staging-cus --resource-group rg-payreality-staging-cus --container payreality-api --tail 100
curl https://ca-payreality-api-staging-cus.lemonbeach-1c496439.centralus.azurecontainerapps.io/health
```

## Getting a shell inside the running container

```
az containerapp exec --name ca-payreality-api-staging-cus --resource-group rg-payreality-staging-cus --command "<single command>"
```

Notes learned in Milestone 4:
- One command per invocation — chaining with `;` inside `--command "sh -c '...'"` hits a quoting error through this CLI's layers. Run separate `exec` calls instead.
- If the app has scaled to zero (`min_replicas=0` and no recent traffic), exec fails with *"Cannot attach to a container that is not running."* Send one `curl .../health` first to trigger a cold start, wait a few seconds, then exec.
- The exec/SSH endpoint has its own rate limit, independent of the application: a burst of calls can return `429` with a `Retry-After` of up to 600 seconds. Space out exec sessions during any investigation.
- Useful commands once inside: `curl http://localhost:8181/health` (OPA), `curl http://localhost:8181/v1/policies` (loaded policy bundle), `python -m alembic current` (migration state).

## Restarting the application

```
az containerapp revision restart --name ca-payreality-api-staging-cus --resource-group rg-payreality-staging-cus --revision <revision-name>
```

Confirmed clean in Milestone 4: full startup sequence (OPA init → migrations, idempotent → uvicorn) re-runs correctly, `/health` returns `200` within ~15 seconds.

## Load testing this environment

The application has an existing, in-process, per-client-IP rate limiter (120 req/60s per IP, `server/app/security.py`) applied to every route. A load-testing tool that doesn't vary its source IP will trip this after ~120 requests and mostly measure the rate limiter, not the infrastructure. To measure real infra performance, vary the `X-Forwarded-For` header per simulated client (the rate limiter keys on it) — a working example script from Milestone 4 is described in `MILESTONE_4_PERFORMANCE_REPORT.md`.

Never direct load tests at the Render production URL beyond a handful of light, sequential requests for comparison — see this program's own absolute rules.

## Setting a real secret

```
az keyvault secret set --vault-name kv-pr-staging-lu2swm --name evidence-signing-key-b64 --value "<real value>"
```

Never via `terraform apply` — every application secret has `lifecycle { ignore_changes = [value] }` specifically so this doesn't get silently overwritten by an unrelated future apply.

## Rotating the Terraform-operator's Key Vault / Storage access

Both roles (`Key Vault Secrets Officer`, `Storage Blob Data Contributor`) are granted to `data.azurerm_client_config.current.object_id` — whoever is signed in via `az login` when Terraform runs. A new operator identity (e.g. a CI service principal) needs both roles granted before its first `terraform apply` against either module, and should expect the 30-second `time_sleep` for RBAC propagation already built into both modules.

## If a Key Vault or Storage Account name collision happens again

Do not attempt to purge or recover a soft-deleted vault to reclaim its name — purge protection makes this impossible before the retention window elapses, and recovery re-binds the vault to its original region. The dedicated `random_string.key_vault_suffix` generates a fresh, collision-resistant name on the next `terraform apply` from a clean state instead.

## Checking backup / recovery posture

```
az postgres flexible-server show --name psql-payreality-staging-cus --resource-group rg-payreality-staging-cus --query "backup"
```

`earliestRestoreDate` being populated confirms a real, usable PITR restore point exists. A full restore-to-new-server drill has not yet been rehearsed (see Risk Register) — if performing one, be aware it creates a new, permanent Postgres server under this program's no-deletion rule; scope and approve that explicitly before running it.

## Querying logs and telemetry

```
WSID=$(az monitor log-analytics workspace show --resource-group rg-payreality-staging-cus --workspace-name log-payreality-staging-cus --query customerId -o tsv)
az monitor log-analytics query --workspace "$WSID" --analytics-query "ContainerAppConsoleLogs_CL | take 20"
```

Application Insights (`appi-payreality-staging-cus`) currently receives **no** application-level telemetry — don't expect data there until APM instrumentation is added to the application (see Known Issues / Risk Register). Log Analytics is where real observability lives today.

## Alerts

None exist yet beyond App Insights' auto-created Smart Detection action group. Before relying on this environment operationally, configure at minimum: Container App unhealthy/restart-looping, Postgres unreachable, Key Vault access-denied spike — see `MILESTONE_4_OPERATIONAL_READINESS_REPORT.md`'s recommendation.

## Known environment quirks (this workstation)

- Git Bash mangles Azure resource IDs starting with `/subscriptions/...` into Windows paths — prefix `MSYS_NO_PATHCONV=1`.
- `python3` resolves to a native Windows Python here; use `C:/...` paths, not Git Bash's `/c/...` MSYS paths, when a script opens a file.
- Several `az` subcommands (`app-insights`, `log-analytics`) need a CLI extension — install non-interactively with `az extension add --name <ext> --yes` to avoid a prompt that fails in a non-interactive shell.
