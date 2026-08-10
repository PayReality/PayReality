# Milestone 3: Environment Verification

Every check below is a live command against the real `rg-payreality-staging-cus` environment, run during this milestone, not inferred from Terraform config.

## Resource Groups

`az group exists --name rg-payreality-staging-cus` → confirmed via `az resource list` returning 22 top-level resources, all `centralus` or `global` (DNS). `rg-payreality-staging-eus2` confirmed fully deleted (`az group exists` → `false`).

## Container Registry

`acrprstagingadzg.azurecr.io`, Standard SKU. `payreality-api:staging-3f34349` present with digest `sha256:361fdd2d29...5f27` (`az acr repository show`). `AcrPull` (Container App identity) and `AcrPush` (CI/CD identity) roles confirmed via `az role assignment list` scoped to the registry.

## Container Apps Environment / App

Environment `cae-payreality-staging-cus`: `Succeeded`, VNet-integrated into `snet-payreality-containerapps-staging-cus`. App `ca-payreality-api-staging-cus`: `provisioningState=Succeeded`, `runningStatus=Running`, active revision `--0000001` with 1 replica. Public FQDN `ca-payreality-api-staging-cus.lemonbeach-1c496439.centralus.azurecontainerapps.io`.

- `curl .../health` → `200 {"status":"ok"}`
- `curl .../health/ready` → `200` (this probe itself calls through to OPA at `127.0.0.1:8181/health` — see below)

## PostgreSQL Flexible Server

`psql-payreality-staging-cus`: `state=Ready`, FQDN `psql-payreality-staging-cus.postgres.database.azure.com`, `publicNetworkAccess=Disabled`, VNet-integrated via `snet-payreality-postgres-staging-cus`. Database `payreality` present, empty of data (no migration performed, per this milestone's own instruction) but schema fully current — confirmed by the application's own Alembic run at startup, which chained all 18 migrations from empty to head (`d7e28b4c91a6`) without error.

## Blob Storage

`stprstagingadzg`: `allowBlobPublicAccess=false`, `minimumTlsVersion=TLS1_2`, `enableHttpsTrafficOnly=true`, `publicNetworkAccess=Enabled` (identity-gated, see Security Review). Three containers present (`uploads`, `evidence-exports`, `authorization-receipts`), all `private` access type. Unauthenticated container listing → `409` (no anonymous read).

## Key Vault

`kv-pr-staging-lu2swm`: `enableRbacAuthorization=true`, `enablePurgeProtection=true`, `publicNetworkAccess=Enabled` (identity-gated). All 5 secrets present (4 application placeholders + `postgres-administrator-password` + `database-url` from `modules/postgres` — 6 total). Unauthenticated secret list → `401`. The Container App's successful Postgres migration at startup is live proof the managed-identity secret-retrieval path (`database-url` → env var `DATABASE_URL`) works end-to-end, not just that the role exists.

## Managed Identities

`id-payreality-containerapp-staging-cus` and `id-payreality-cicd-staging-cus`, both `Succeeded`. Federated credential for GitHub Actions OIDC present on the CI/CD identity.

## Log Analytics / Application Insights / Azure Monitor

`log-payreality-staging-cus`: workspace live, **genuinely receiving data** — confirmed via a direct KQL query, not just "diagnostic setting exists":
- `ContainerAppConsoleLogs_CL`: real container stdout, including the exact OPA startup line and live `/health` request logs.
- `AzureDiagnostics`: 3,090 rows from Postgres, 75 from Key Vault.

`appi-payreality-staging-cus`: resource provisioned (`provisioningState=Succeeded`), but its `requests` table is **empty** — see Known Issues. Azure Monitor alert rules were explicitly not configured, per this milestone's own scope.

## Networking

VNet `vnet-payreality-staging-cus` with three delegated subnets (container-apps, postgres, private-endpoints). Both private endpoints (`pe-kv-pr-staging-lu2swm`, `pe-stprstagingadzg-blob`) show `connectionStatus=Approved`. Both private DNS zones linked to the VNet. Outbound internet confirmed (ACR pull succeeded from inside the Container Apps environment; OPA's own "out of date" check reached `openpolicyagent.org`). Ingress confirmed via the public health-check curls above. Managed identity token flow confirmed by the successful Key-Vault-secret-backed startup.

## Diagnostic Settings

All 5 targets present and returning `Succeeded`: Postgres, Key Vault, Storage (targeted at `blobServices/default`, not the account — see Deployment Report), Container Apps Environment, Container Registry.

## Terraform state

`terraform plan` against the final configuration: **"No changes. Your infrastructure matches the configuration."** Zero drift.
