# Authority Intelligence Program, Phase 1: the retrieval layer for
# Authority Builder's document corpus (SOPs, delegation-of-authority
# memos, approval matrices, governance/regulatory documents -- never
# Runtime Evidence, Runtime Truth, or live customer data, none of which
# this module or the application code that calls it ever touches).

resource "azurerm_search_service" "this" {
  name                = var.search_service_name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku

  # RBAC-only, no shared admin/query keys -- consistent with this
  # program's own security requirement ("no API keys inside code... no
  # shared credentials") and the identity-first model already
  # established for Key Vault, Storage, and (this same program)
  # Cognitive Services.
  local_authentication_enabled = false

  # Identity-first, same decision as modules/ai-foundry and Key
  # Vault/Storage before it: RBAC is the boundary, not network
  # isolation.
  public_network_access_enabled = true

  tags = merge(var.tags, { Purpose = "Retrieval index for Authority Intelligence's governance-document corpus, ${var.environment}" })
}

# Two roles, not one: index/document *management* (creating the index
# itself, app/services/authority_intelligence_service.py's
# ensure_search_index) is a control-plane operation Search Index Data
# Contributor does not cover -- Search Service Contributor is the
# narrowest built-in role that does.
resource "azurerm_role_assignment" "container_app_search_service_contributor" {
  scope                = azurerm_search_service.this.id
  role_definition_name = "Search Service Contributor"
  principal_id         = var.container_app_identity_principal_id
}

# Reading and writing documents within that index (index_document,
# retrieve_corpus_text) is the data-plane operation this role covers.
resource "azurerm_role_assignment" "container_app_search_index_data_contributor" {
  scope                = azurerm_search_service.this.id
  role_definition_name = "Search Index Data Contributor"
  principal_id         = var.container_app_identity_principal_id
}
