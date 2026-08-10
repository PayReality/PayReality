# Milestone 3: Operational Checklist

Practical reference for anyone operating or re-deploying this environment.

## Re-running Terraform against this environment

```
cd AZURE_MIGRATION/terraform
terraform init \
  -backend-config="resource_group_name=rg-payreality-tfstate" \
  -backend-config="storage_account_name=sttfstatepr8p3t4s" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=payreality-staging.tfstate"
terraform plan -var-file="environments/staging.tfvars"
```

Always review the plan before applying. `terraform.exe` on this workstation is at
`C:\Users\user\AppData\Local\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe\terraform.exe`
— not on `PATH` in Git Bash; reference it directly or add it to `PATH`.

## Building and deploying a new application image

```
az acr build --registry acrprstagingadzg --image payreality-api:staging-<short-sha> server/
```

Then update `container_image` in `environments/staging.tfvars` to the new tag and re-apply. If `az acr build`'s log streaming crashes locally (a known Windows console-encoding issue, not a build failure — see Known Issues #4), confirm the real status with `az acr task list-runs --registry acrprstagingadzg --top 3 -o table` rather than assuming failure.

## Checking the running application

```
az containerapp logs show --name ca-payreality-api-staging-cus --resource-group rg-payreality-staging-cus --container payreality-api --tail 100
curl https://ca-payreality-api-staging-cus.lemonbeach-1c496439.centralus.azurecontainerapps.io/health
```

## Setting a real secret (Milestone 5's mechanism, usable any time it's needed)

```
az keyvault secret set --vault-name kv-pr-staging-lu2swm --name evidence-signing-key-b64 --value "<real value>"
```

Never via `terraform apply` — every application secret has `lifecycle { ignore_changes = [value] }` specifically so this doesn't get silently overwritten.

## Rotating the Terraform-operator's Key Vault / Storage access

Both roles (`Key Vault Secrets Officer`, `Storage Blob Data Contributor`) are granted to `data.azurerm_client_config.current.object_id` — i.e., whoever is signed in via `az login` when Terraform runs. If the operator identity changes (e.g., moving to a service principal for CI), that principal needs both roles granted before its first `terraform apply` against either module, and should expect the 30-second `time_sleep` for RBAC propagation already built into both modules.

## If a Key Vault or Storage Account name collision happens again

Do not attempt to purge or recover a soft-deleted vault to reclaim its name — purge protection makes this impossible before the retention window elapses, and recovery re-binds the vault to its original region. Instead, let the naming convention's dedicated random suffix (`random_string.key_vault_suffix`) generate a new name on the next `terraform apply` from a clean state.

## Known transient environment quirks

- Git Bash mangles Azure resource IDs that start with `/subscriptions/...` into Windows paths. Prefix the command with `MSYS_NO_PATHCONV=1` when passing a raw resource ID to `az`.
- `python3` on this workstation resolves to a native Windows Python; pass Windows-style paths (`C:/...`), not Git Bash's `/c/...` MSYS paths, when a script needs to open a file.
- Several `az` subcommands (`app-insights`, `log-analytics`) require a CLI extension; install non-interactively with `az extension add --name <ext> --yes` to avoid an interactive prompt that fails in a non-interactive shell.
