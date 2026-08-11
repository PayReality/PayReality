# Azure Runbook

**Status:** living document, first published Milestone 4, revised Milestone 5 (every command in this file re-run and confirmed against the live environment as part of that milestone). Supersedes `MILESTONE_3_OPERATIONAL_CHECKLIST.md` as the day-to-day reference (that file remains as the historical record of what Milestone 3 knew at the time); update this file, not that one, as operational knowledge grows.

Current environment: staging only, `rg-payreality-staging-cus`, `centralus`. No production environment exists yet — see `MILESTONE_5_PRODUCTION_CUTOVER_REPORT.md` for the current go/no-go decision.

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

**Getting the Container App to actually pick up the new value (Milestone 5 finding):** setting the secret in Key Vault is necessary but not sufficient.

1. All application secrets are wired to the Container App as **versionless** Key Vault URIs (`modules/key-vault/outputs.tf`, `modules/postgres/outputs.tf`) specifically so a new value doesn't require a `terraform apply` to be referenced. If you ever see a bare `terraform apply` needed just to pick up a rotated value, something regressed back to a versioned (`.id`) reference — fix it there, not by hand.
2. Even with a versionless reference, a plain `az containerapp revision restart` on the **same** revision was observed to be **unreliable** at picking up the newly-set value within the same testing session — sometimes it did, sometimes the old value persisted. The **reliable** method confirmed this milestone is to force a genuinely new revision:
   ```
   az containerapp revision copy --name ca-payreality-api-staging-cus --resource-group rg-payreality-staging-cus --revision-suffix <short-label>
   ```
3. Verify the fix actually landed before moving on — don't trust a `200` on `/health` alone (it doesn't check secret-dependent state). For the signing key specifically:
   ```
   curl https://<container-app-fqdn>/v1/evidence/verification-key
   ```
   and confirm `public_key_b64` matches what you expect (derive it locally with the same `nacl.signing.SigningKey` the app uses, from `app/domain/evidence/signing.py`'s `public_key_b64_from_signing_key_b64`).
4. **A subtle bash trap that cost real time in Milestone 5:** extracting a value from a `KEY=value` line with `cut -d= -f2` silently truncates anything after a *second* `=` in the value itself — and base64 strings routinely end in `=` padding. Use `cut -d= -f2-` (note the trailing dash) or `sed 's/^KEY=//'` instead. Always verify the extracted value's length/content before feeding it to `az keyvault secret set`.

## Rotating the Terraform-operator's Key Vault / Storage access

Both roles (`Key Vault Secrets Officer`, `Storage Blob Data Contributor`) are granted to `data.azurerm_client_config.current.object_id` — whoever is signed in via `az login` when Terraform runs. A new operator identity (e.g. a CI service principal) needs both roles granted before its first `terraform apply` against either module, and should expect the 30-second `time_sleep` for RBAC propagation already built into both modules.

## If a Key Vault or Storage Account name collision happens again

Do not attempt to purge or recover a soft-deleted vault to reclaim its name — purge protection makes this impossible before the retention window elapses, and recovery re-binds the vault to its original region. The dedicated `random_string.key_vault_suffix` generates a fresh, collision-resistant name on the next `terraform apply` from a clean state instead.

## Checking backup / recovery posture

```
az postgres flexible-server show --name psql-payreality-staging-cus --resource-group rg-payreality-staging-cus --query "backup"
```

`earliestRestoreDate` being populated confirms a real, usable PITR restore point exists.

## Performing a PITR restore (rehearsed and confirmed working, Milestone 5)

```
az postgres flexible-server restore --resource-group rg-payreality-staging-cus \
  --name <new-server-name> --source-server psql-payreality-staging-cus
```

Omitting `--restore-time` restores to the current point. This creates a **new, separate, permanent Postgres server** (Flexible Server restore never restores in place) — VNet/subnet/private-DNS configuration carries over from the source automatically, no extra flags needed. Confirmed via a real drill: the restored server matched the source's exact Alembic head revision and row counts in `organizations`/`signing_keys`, verified by connecting from inside the VNet (see "Getting a shell inside the running container," then run a `python -c "import psycopg; ..."` one-liner against the restored server's FQDN using the admin password from the `postgres-administrator-password` Key Vault secret). Because this creates a real, ongoing-cost resource that this program's own rules don't authorize deleting without explicit approval, get that approval before running a restore drill, and expect to either keep or explicitly get sign-off to delete the resulting server afterward.

## Rollback plan (tested live, Milestone 5)

**What actually happens when a bad image is deployed:** confirmed via a real, deliberate test (deploying a nonexistent image tag through Terraform). The new revision provisions at the ARM level (`provisioningState: Provisioned`) but never gets a running replica (`runningState: ActivationFailed`, `replicas: 0`). Even though Container Apps' ingress traffic configuration shows the broken revision holding 100% weight, **it kept serving `/health` at `200` from the previous healthy revision throughout** — a bad deploy alone did not cause an outage in this test. Do not assume this is a hard guarantee for every failure mode (this tested "image doesn't exist," not "image exists but the app crashes after passing an initial check"), but it is a real, observed safety behavior of Container Apps in `revision_mode = "Single"`.

**How to roll back:**

1. Confirm there's actually a problem before rolling back — check `az containerapp revision list ... --query "[].{name:name, healthState:properties.healthState}"`. If the previous revision is still `Healthy` and serving (see above), you may have more time than it feels like.
2. The correct rollback is through Terraform, since it's this project's source of truth: set `container_image` in `environments/staging.tfvars` back to the last known-good tag (image tags are immutable and never overwritten — every build gets its own `staging-<commit-sha>` tag, so the previous good value is always known from git history or the previous `terraform apply`'s recorded plan), then `terraform plan` → review → `terraform apply` exactly as any other change.
3. This creates yet another new revision (Container Apps doesn't "revert" to an old revision object, it always creates a new one from the given template) — confirmed in the live test: rolling back produced revision `--0000004`, not a reactivation of `--0000002`, both ending up on the same known-good image.
4. Verify recovery the same way as any deploy: `/health` returns `200`, `az containerapp revision list` shows the new revision `Healthy` with `replicas: 1`, and `/version` reflects the expected build.
5. Clean up the failed revision if it doesn't auto-deactivate: `az containerapp revision deactivate --name ... --revision <bad-revision-name>` (confirmed in testing that Azure sometimes does this automatically once a newer healthy revision exists).

**Do not use `terraform apply -auto-approve` for this or any change** — it was blocked by this environment's own permission controls during testing specifically because it skips plan review; use the plan-file pattern (`terraform plan -out=x.tfplan` then `terraform apply x.tfplan`) instead, which this whole program has used throughout.

## Querying logs and telemetry

```
WSID=$(az monitor log-analytics workspace show --resource-group rg-payreality-staging-cus --workspace-name log-payreality-staging-cus --query customerId -o tsv)
az monitor log-analytics query --workspace "$WSID" --analytics-query "ContainerAppConsoleLogs_CL | take 20"
```

Application Insights (`appi-payreality-staging-cus`) is now fully instrumented as of Milestone 5 (`server/app/observability.py`, active whenever `APPLICATIONINSIGHTS_CONNECTION_STRING` is set — which it is, in this Container App). Query it directly:

```
az monitor app-insights query --app appi-payreality-staging-cus --resource-group rg-payreality-staging-cus \
  --analytics-query "requests | where timestamp > ago(15m) | order by timestamp desc | take 20"
```

`requests`, `dependencies` (DB calls via SQLAlchemy auto-instrumentation), and `traces` (log correlation) all carry real data. Render never sets that environment variable, so nothing changed there.

## Alerts

Five metric alerts exist as of Milestone 5 (`modules/alerts`), all notifying `ag-payreality-<environment>-critical` by email: Postgres unavailable (Sev 0), Postgres storage >85% (Sev 2), Container App restart (Sev 1), Container App CPU >80% (Sev 2), Key Vault availability <95% (Sev 1).

**Testing the notification path** (confirmed working, Milestone 5):
```
az monitor action-group test-notifications create --action-group ag-payreality-staging-critical \
  --resource-group rg-payreality-staging-cus -a email primary-oncall <email> usecommonalertsChema \
  --alert-type metricstaticthreshold
```
Poll the returned operation until `state: Complete`; check `actionDetails[].Status` for `Succeeded`.

**A real limitation found while testing rule evaluation itself:** the `RestartCount` metric tracks platform-detected crash/health-probe-failure restarts, not `az containerapp revision restart` (a deliberate CLI-initiated restart did not move this metric at all in testing). Don't use a manual restart as a way to test that specific alert; a genuine crash-loop or the rollback-plan test above (which produces an `ActivationFailed` revision, a different metric) are more representative. The CPU-high alert also proved hard to trigger organically against the lightweight `/health` endpoint even under sustained load (~15 req/s for over 3 minutes kept CPU under 5% on the 0.5-vCPU allocation) — if you need to test it for real, target a heavier, DB-touching endpoint instead.

## Monitoring dashboard

`dash-payreality-staging` (`modules/dashboard`) gives an at-a-glance view of Container App / Postgres / Key Vault. Get the direct link from Terraform's own output:
```
terraform output monitoring_dashboard_url
```

## Known environment quirks (this workstation)

- Git Bash mangles Azure resource IDs starting with `/subscriptions/...` into Windows paths — prefix `MSYS_NO_PATHCONV=1`.
- `python3` resolves to a native Windows Python here; use `C:/...` paths, not Git Bash's `/c/...` MSYS paths, when a script opens a file.
- Several `az` subcommands (`app-insights`, `log-analytics`) need a CLI extension — install non-interactively with `az extension add --name <ext> --yes` to avoid a prompt that fails in a non-interactive shell.
- The Azure Resource Manager control plane itself occasionally returns a transient `503 Service Unavailable` HTML page on an otherwise-correct `az` command (observed once, Milestone 5, on `az containerapp replica list`) — retry once before assuming the command or resource is actually broken.
- `terraform apply -auto-approve` was blocked by this environment's own permission controls (it skips plan review). Use the plan-file pattern instead; it has worked for every apply across every milestone of this program.
