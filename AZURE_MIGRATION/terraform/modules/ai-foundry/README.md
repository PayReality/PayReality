# Module: ai-foundry

**Owner:** platform/infrastructure engineer. **Purpose:** the Authority Intelligence Program's Azure AI Foundry footprint -- backs `app/domain/ai_provider/azure_foundry_provider.py`, the AIProvider implementation the AI Authority Builder prefers once this module is applied (falling back to Anthropic, then the Fake provider, if it isn't -- see `routers/ai_authority_builder.py`'s `_provider()`).

## What this module creates

One `azurerm_cognitive_account` (`kind = "OpenAI"` -- the pinned `azurerm ~> 3.117` provider predates the newer `"AIServices"` multi-service kind, confirmed via `terraform validate`'s own accepted-kind list; `"OpenAI"` is also the correct kind for an OpenAI-format model regardless) and one `azurerm_cognitive_deployment` (a single model deployment, `gpt-5-mini` by default, `GlobalStandard` scale -- confirmed via `az cognitiveservices account list-models` that plain regional `Standard` capacity isn't sold in `centralus`, and that the originally-chosen `gpt-4o-mini` no longer accepts new deployments at all: its only version is in Azure's `Deprecating` lifecycle state, which blocks `CreateOrUpdate` with a `ServiceModelDeprecating` error -- confirmed live, on the first staging apply, not assumed in advance. `gpt-5-mini` is `GenerallyAvailable` in this account/region and is the model catalog's direct current equivalent). One role assignment: `Cognitive Services User`, granted only to the Container App's own Managed Identity.

## Why this, not a full AI Foundry Hub + Project

A Hub/Project (`azurerm_machine_learning_workspace`, `kind = "Hub"`, plus a Project sub-resource) is Azure's model for multi-project ML Studio scenarios -- shared compute, multiple connected data sources, several projects collaborating. Authority Intelligence has exactly one inference need (structured extraction from a document corpus), so a Cognitive Services account with one deployment is the correctly-sized resource, not an under-provisioned shortcut. If a genuine second AI use case with its own project-level isolation need arises later, adding a Hub/Project at that point is a clean, additive change -- this module doesn't need to anticipate it now.

## Why identity-first, not a private endpoint

The same decision already made and approved for Key Vault and Storage (Milestone 3): Azure RBAC + Managed Identity is the real security boundary here, not network isolation. `public_network_access_enabled = true`, no private endpoint, no VNet requirement for whoever manages this resource -- only the `Cognitive Services User` role, granted to exactly one identity, controls who can call it. This keeps the resource's access model consistent with the rest of this project rather than introducing a second, network-isolation-based pattern for one new service.

## Inputs / Outputs

Standard `resource_group_name`/`location`/`environment`/`tags`, plus `container_app_identity_principal_id` (the one identity granted access) and three model-choice variables (`deployment_name`, `model_name`, `model_version`, `sku_capacity`) with pilot-appropriate defaults. Outputs the endpoint (a plain value, not a secret -- Managed Identity is the actual credential) and the deployment name.
