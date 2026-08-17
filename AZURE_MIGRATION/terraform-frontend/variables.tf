variable "location" {
  description = "Azure region for both Static Web Apps. Reuses the same region as the backend for operator familiarity, though Static Web Apps are edge-served globally regardless of this setting."
  type        = string
  default     = "centralus"
}

variable "location_short" {
  type    = string
  default = "cus"
}

variable "resource_group_name" {
  description = "Reuses the existing prod resource group (rg-payreality-prod-cus) rather than creating a new one -- two Static Web Apps add negligible resource-group clutter, and a dedicated RG would be complexity with no corresponding benefit for a resource type with no networking/lifecycle coupling to anything else in that group."
  type        = string
  default     = "rg-payreality-prod-cus"
}

variable "sku_tier" {
  description = "Free tier: 2 custom domains per app (exactly enough for the marketing site's apex+www), no staging-slot feature needed since this project creates fully separate Static Web App resources per environment instead of relying on SWA's own built-in preview-environment feature."
  type        = string
  default     = "Free"
}

variable "github_repository_website" {
  type    = string
  default = "PayReality/Payreality-website"
}

variable "github_repository_dashboard" {
  type    = string
  default = "PayReality/PayReality"
}

variable "tags" {
  type = map(string)
  default = {
    Application = "PayReality"
    ManagedBy   = "Terraform"
    Purpose     = "Milestone 16: Vercel to Azure frontend hosting migration"
  }
}
