# Module: managed-identity

**Owner:** platform/infrastructure engineer. **Purpose:** the one identity the Container App uses to authenticate to every other Azure service, so no secret value (a connection string, a registry password, a storage key) ever needs to be handed to the application directly.

## What this module creates

**Two** user-assigned identities, deliberately separate:
1. The Container App's runtime identity (`azurerm_user_assigned_identity.container_app`).
2. A CI/CD identity (`azurerm_user_assigned_identity.cicd`) for GitHub Actions, plus a federated identity credential trusting GitHub's OIDC issuer for one named repository and one named branch only — no client secret to generate, store, rotate, or leak.

Nothing else — this module deliberately does not grant any role assignment; see below.

## Why two identities, not one

Least privilege, not convenience: the running application should never hold permission to push a new container image or trigger a deployment, and a CI pipeline should never hold `Key Vault Secrets User` or `Storage Blob Data Contributor`. One identity asked to be trusted for both would violate Absolute Rule 10 ("every resource must have a clear owner and purpose") the moment either purpose needed auditing separately from the other.

## Why user-assigned, not system-assigned

A system-assigned identity's lifecycle is tied to its parent resource: delete the Container App, the identity (and every role assignment on it) is gone. A user-assigned identity survives independently, which matters the moment a Container App revision is replaced rather than updated in place — the identity, and everything it's been granted access to, doesn't need re-granting.

## Why role assignments live elsewhere

Each resource this identity needs access to (Container Registry, Key Vault, Storage) grants that access inside its own module, using this module's `principal_id` output as an input. This keeps "who can access this Key Vault" answerable by reading `modules/key-vault` alone, never by reading a separate, central "here's everything granted to everything" file that drifts from the resources it describes.

## Inputs

| Name | Type | Required |
|---|---|---|
| `identity_name`, `cicd_identity_name` | string | yes |
| `resource_group_name`, `location`, `environment`, `tags` | — | yes |
| `github_repository` | string | no — blank skips creating the federated credential entirely |
| `github_deploy_branch` | string | no — default `main` |

## Outputs

| Name | Consumed by |
|---|---|
| `id` | `modules/container-apps` (assigns the runtime identity to the Container App) |
| `principal_id` | `modules/key-vault`, `modules/storage`, `modules/container-registry`'s AcrPull assignment (role assignments for the **runtime** identity) |
| `client_id` | The application itself, via a Container App environment variable (`AZURE_CLIENT_ID`), so the Azure SDK's `DefaultAzureCredential` knows which user-assigned identity to use when more than one might be attached |
| `name` | Diagnostics/logging only |
| `cicd_principal_id` | `modules/container-registry`'s AcrPush assignment |
| `cicd_client_id` | Not consumed by anything in this milestone — reserved for the future GitHub Actions workflow's `azure/login` step |
| `cicd_name` | Diagnostics/logging only |
