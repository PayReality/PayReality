variable "log_analytics_name" {
  type = string
}

variable "app_insights_name" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "environment" {
  type = string
}

variable "tags" {
  type = map(string)
}

variable "log_retention_days" {
  description = "30 by default. Raise for prod if a compliance requirement (out of this program's scope, per its own stop condition) ever names a longer log-retention window; 30 is proportionate to today's operational need (debugging, not audit)."
  type        = number
  default     = 30
}
