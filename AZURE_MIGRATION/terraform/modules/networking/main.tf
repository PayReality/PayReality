# Three subnets, one VNet, deliberately not more:
#   - container-apps: delegated to Microsoft.App/environments, sized /23
#     so a future move from the consumption plan to workload profiles
#     (Milestone 6+'s "future horizontal scaling" note) doesn't require
#     re-carving the address space.
#   - postgres: delegated to Microsoft.DBforPostgreSQL/flexibleServers,
#     Flexible Server's own VNet-integration mechanism -- no separate
#     Private Endpoint resource needed for Postgres specifically (see
#     modules/postgres/README.md).
#   - private-endpoints: undelegated, for standard Private Endpoint NICs
#     (Key Vault, Storage). Not used by Postgres, which doesn't need it.

resource "azurerm_virtual_network" "this" {
  name                = var.vnet_name
  resource_group_name = var.resource_group_name
  location            = var.location
  address_space       = var.vnet_address_space
  tags                = merge(var.tags, { Purpose = "Network boundary for all PayReality ${var.environment} resources" })
}

resource "azurerm_subnet" "container_apps" {
  name                 = var.subnet_container_apps_name
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_container_apps_cidr]

  delegation {
    name = "container-apps-delegation"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "postgres" {
  name                 = var.subnet_postgres_name
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_postgres_cidr]

  delegation {
    name = "postgres-flexible-server-delegation"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_subnet" "private_endpoints" {
  name                 = var.subnet_private_endpoints_name
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_private_endpoints_cidr]
}

# Generic privatelink DNS zones -- Key Vault and Storage both resolve
# through these once their Private Endpoints exist (modules/key-vault,
# modules/storage). Postgres has its own, differently-shaped zone,
# created inside modules/postgres because its name is tied to the server
# resource itself, not a fixed, reusable zone name the way these two are.

resource "azurerm_private_dns_zone" "key_vault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { Purpose = "DNS resolution for Key Vault private endpoints" })
}

resource "azurerm_private_dns_zone_virtual_network_link" "key_vault" {
  name                  = "link-${var.vnet_name}-kv"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.key_vault.name
  virtual_network_id    = azurerm_virtual_network.this.id
  registration_enabled  = false
}

resource "azurerm_private_dns_zone" "blob_storage" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { Purpose = "DNS resolution for Storage Account (Blob) private endpoints" })
}

resource "azurerm_private_dns_zone_virtual_network_link" "blob_storage" {
  name                  = "link-${var.vnet_name}-blob"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.blob_storage.name
  virtual_network_id    = azurerm_virtual_network.this.id
  registration_enabled  = false
}
