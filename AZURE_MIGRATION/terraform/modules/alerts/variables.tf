variable "resource_group_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "notification_email" {
  description = "Where alert notifications are sent. No default -- every environment must consciously set this rather than silently alerting no one, which is exactly the gap this module exists to close (see MILESTONE_4_RISK_REGISTER.md #1)."
  type        = string
}

variable "container_app_id" {
  type = string
}

variable "postgres_id" {
  type = string
}

variable "key_vault_id" {
  type = string
}
