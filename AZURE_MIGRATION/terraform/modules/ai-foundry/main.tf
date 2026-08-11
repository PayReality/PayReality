# Authority Intelligence Program, Phase 1: the minimal Azure AI Foundry
# footprint for a single inference need. `azurerm_cognitive_account`
# (kind = "AIServices") + one `azurerm_cognitive_deployment` is the
# modern, minimal way to get a Foundry model-catalog deployment behind a
# real endpoint -- deliberately NOT a full AI Foundry Hub +
# Project (`azurerm_machine_learning_workspace`, kind = "Hub"), which is
# built for multi-project ML Studio scenarios this program's one
# extraction use case doesn't have. Adding a heavier Hub/Project later,
# if a genuine multi-project need arises, is straightforward -- starting
# with one is not "unnecessary Azure resources" avoidance, it's sizing
# the resource to the actual, stated need (Phase 1's own instruction).

resource "azurerm_cognitive_account" "this" {
  name                = var.account_name
  resource_group_name = var.resource_group_name
  location            = var.location
  # "OpenAI", not the newer "AIServices" multi-service kind: this
  # provider version (~> 3.117, pinned project-wide since Milestone 2)
  # predates AIServices support -- confirmed via `terraform validate`'s
  # own accepted-kind list, not assumed. OpenAI is the correct kind for
  # an OpenAI-format model deployment (var.model_name's default,
  # gpt-5-mini) regardless -- this is not a scope reduction, just the
  # provider-version-correct resource kind for the same model.
  kind     = "OpenAI"
  sku_name = "S0"

  # A custom subdomain is required for token-based (Managed Identity)
  # authentication against Cognitive Services accounts at all -- without
  # one, only key-based auth is possible, which this program's own
  # security requirement ("no API keys inside code... no shared
  # credentials") rules out.
  custom_subdomain_name = var.account_name

  # Identity-first, same decision already made and approved for Key
  # Vault and Storage (Milestone 3): Azure RBAC is the real boundary,
  # not network isolation -- no private endpoint, no VNet requirement
  # for whoever manages this resource, only the Managed Identity roles
  # granted below control who can actually call it.
  public_network_access_enabled = true

  tags = merge(var.tags, { Purpose = "Azure AI Foundry account backing Authority Intelligence's extraction provider for ${var.environment}" })
}

resource "azurerm_cognitive_deployment" "this" {
  name                 = var.deployment_name
  cognitive_account_id = azurerm_cognitive_account.this.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  # `scale`, not the newer `sku` block: same provider-version constraint
  # as the `kind` fix above -- `~> 3.117` predates azurerm's rename of
  # this block to `sku`. Same arguments, same meaning, just the older
  # block name this pinned version actually understands.
  #
  # "GlobalStandard", not "Standard": confirmed directly via
  # `az cognitiveservices account list-models` against this account --
  # this model family in centralus only offers GlobalStandard,
  # GlobalBatch/DataZoneBatch, DataZoneStandard, and
  # GlobalProvisionedManaged. Plain regional "Standard" capacity isn't
  # sold in centralus at all (first apply attempt failed with exactly
  # this 400). Global routing is fine here -- this program has no
  # data-residency requirement, and it's the standard low-friction,
  # pay-as-you-go choice.
  scale {
    type     = "GlobalStandard"
    capacity = var.sku_capacity
  }
}

# The Container App's own identity is the only identity that can call
# this deployment -- no key ever leaves Key Vault (there is no key to
# leave; nothing sensitive is stored there for this resource at all).
resource "azurerm_role_assignment" "container_app_cognitive_services_user" {
  scope                = azurerm_cognitive_account.this.id
  role_definition_name = "Cognitive Services User"
  principal_id         = var.container_app_identity_principal_id
}
