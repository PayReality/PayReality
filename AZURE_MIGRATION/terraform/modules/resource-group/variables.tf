variable "name" {
  description = "Resource group name, already fully computed by the root module's naming convention."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "environment" {
  description = "Deployment environment, used only in this resource's Purpose tag."
  type        = string
}

variable "tags" {
  description = "Common tags map from the root module."
  type        = map(string)
}
