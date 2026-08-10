resource "azurerm_resource_group" "this" {
  name     = var.name
  location = var.location
  tags     = merge(var.tags, { Purpose = "Container for every PayReality ${var.environment} resource" })
}
